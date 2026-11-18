"""FitPlate: a multilingual Streamlit conversation and application shell."""

import base64
import hashlib
import html
import io
import json
from datetime import date
from pathlib import Path

from fitplate.photo_upload import normalize_photo, PhotoError, MAX_PHOTO_BYTES
from fitplate.audio_upload import AUDIO_SUFFIXES
from fitplate.voice_input import voice_input
from fitplate.ui import st
import streamlit as native_st
from fitplate.i18n import tr,language,LANGUAGES,localize_framework_controls,has_english_prose
from PIL import Image, UnidentifiedImageError

from fitplate.domain import PREPARATIONS, UNITS, fresh_draft, today, validate_draft
from fitplate import agent
from fitplate.reference_search import reference_candidates
from fitplate.portion_estimation import portion_options, seed_portion_estimates
from fitplate.source_portions import portions_for, BY_ID as SOURCE_PORTIONS
from fitplate.advanced_ui import cooking_editor, uncertainty_tools, photo_tools
from fitplate.coaching_view import body_profile_editor
from fitplate.coaching import missing_fields
from fitplate.draft_workspace import combine_drafts
from fitplate.weekly_view import weekly_review
from fitplate.meal_transfer_view import transfer_controls
from fitplate.nutrition import DEFAULT_DB, compute_nutrition
from fitplate.nutrition.service import snapshot, daily_summary
from fitplate.nutrition_view import nutrition_panel
from fitplate.meal_estimation import assess_meal, current_notes, clean_notes, DETAIL_ENUMS, detail_fields, questions_for, cautions_for
from fitplate.model_client import ServiceError, load_config
from fitplate.storage import delete_meal, list_meals, read_settings, save_meal, save_settings, read_body_profile

ROOT = Path(__file__).resolve().parent
LOGO = '<img class="brand-mark" src="data:image/svg+xml;base64,' + base64.b64encode((ROOT / "assets/icon.svg").read_bytes()).decode("ascii") + '" alt="" aria-hidden="true">'
st.set_page_config(page_title="FitPlate | Eat with intention", page_icon="assets/icon.svg", layout="wide", initial_sidebar_state="expanded")
st.html(f"<style>{(ROOT / 'assets/styles.css').read_text(encoding='utf-8')}</style>")


def escape(value):
    return html.escape(str(value), quote=True)


def initialize():
    from fitplate.storage import read_language
    if "language" not in st.session_state:
        st.session_state.language=read_language()
    defaults = {
        "page": "Conversation", "draft": None, "draft_queue": [], "messages": [],
        "notice": "", "attachment": None, "upload_revision": 0,
        "draft_revision": 0, "seen_uploads": [],
        "transcripts": {}, "ai_error": "",
        "composer_prefill": None, "voice_ready": None, "pending_media": None,
    }
    for key, value in defaults.items():
        if key not in st.session_state:
            st.session_state[key] = value
    if st.session_state.ai_error.startswith('The AI reply did not match the meal format.'):
        st.session_state.ai_error=''
    st.session_state['_localized_widgets']={}


def navigate(page):
    st.session_state.page = page


def prefill_message(text):
    st.session_state.composer_prefill = tr(text)


def assistant(text,tool_trace=None,sources=None):
    message={"role":"assistant","text":text}
    if tool_trace:message['tool_trace']=tool_trace
    if sources:message['sources']=sources
    st.session_state.messages.append(message)


def receive(text, image=None, source="Text"):
    text = text.strip()[:4000]
    if not text:
        return
    history = list(st.session_state.messages)
    st.session_state.messages.append({"role": "user", "text": "[Meal photo] " + text if image else text})
    st.session_state.ai_error = ""
    try:
        with st.spinner("Reading your meal..." if image else "Thinking..."):
            result = agent.respond(text, draft=st.session_state.draft, history=history,
                                   profile=read_settings(), meals=list_meals(), image=image, source=source, language=language(),body_profile=read_body_profile(),pending_drafts=st.session_state.draft_queue)
    except agent.ConversationError as error:
        assistant(tr(str(error)))
        return False
    except ServiceError as error:
        st.session_state.ai_error = str(error)
        return False
    intent = result["intent"]
    if intent == "meal":
        if result.get('drafts'):
            workspace=combine_drafts(st.session_state.draft,st.session_state.draft_queue,result['drafts'])
            st.session_state.draft=workspace[0]
            st.session_state.draft_queue=workspace[1:]
        else:st.session_state.draft = result["draft"]
        st.session_state.draft_revision += 1
        assistant(result["reply"],result.get('tool_trace'),result.get('sources'))
    elif intent == "discard":
        advance_draft()
        st.session_state.draft_revision += 1
        assistant("Draft discarded. Your saved meals are unchanged.")
    else:
        assistant(result["reply"],result.get('tool_trace'),result.get('sources'))
    return True


def advance_draft():
    queue=st.session_state.draft_queue
    st.session_state.draft=queue.pop(0) if queue else None


def select_draft():
    workspace=combine_drafts(st.session_state.draft,st.session_state.draft_queue,[])
    selected=st.session_state.active_meal_draft
    st.session_state.draft=next(d for d in workspace if d['id']==selected)
    st.session_state.draft_queue=[d for d in workspace if d['id']!=selected]
    st.session_state.draft_revision+=1


def new_custom():
    if st.session_state.draft is None:
        st.session_state.draft = fresh_draft()
    st.session_state.draft["items"].append({"name": "", "quantity": None, "unit": "g", "preparation": "Not specified"})
    st.session_state.draft_revision += 1


def use_typical_estimates():
    for item in st.session_state.draft["items"]:
        item.setdefault("details", {})["use_defaults"] = True
    st.session_state.draft_revision += 1
    assistant("Typical portion and recipe scenarios applied. Review the assumptions below, adjust anything you know, and confirm before saving.")


def estimate_with_ai(meal=None):
    current = st.session_state.draft
    if meal is not None and current is not None and current.get("id") != meal.get("id"):
        st.error("Finish or discard your current draft before estimating another meal.")
        return False
    original = current if current is not None else meal
    try:
        with st.spinner("Estimating food matches and total portions..."):
            result = agent.reestimate(original)
    except ServiceError as error:
        st.error(str(error))
        return False
    st.session_state.draft = result["draft"]
    st.session_state.draft_revision += 1
    assistant(result["reply"])
    st.session_state.notice = "Estimate ready. Review portions and assumptions, then Save meal to update this record."
    navigate("Conversation")
    return True


def change_language():
    from fitplate.storage import save_language
    from fitplate.ui import preserve_widget_values
    preserve_widget_values()
    st.session_state.language=st.session_state.language_choice
    save_language(st.session_state.language)


def open_body_profile():
    st.session_state.open_body_profile=True
    navigate('Goals')


def profile_editor():
    profile = read_settings()
    with st.popover("Preferences", icon=":material/tune:", width="stretch"):
        native_st.selectbox('Language',list(LANGUAGES),index=list(LANGUAGES).index(language()),format_func=lambda code:LANGUAGES[code],key='language_choice',on_change=change_language)
        st.button('Body & training profile',key='profile_shortcut',icon=':material/person:',width='stretch',on_click=open_body_profile)
        st.markdown("**Your preferences**")
        with st.form("profile_form"):
            name = st.text_input("Display name", value=profile["name"], max_chars=40)
            choices = ("Build consistent habits", "Support my training", "Understand my meals")
            focus = st.selectbox("My focus", choices, index=choices.index(profile["focus"]) if profile["focus"] in choices else 0)
            preferences = st.text_input("Food preferences", value=profile["preferences"], placeholder="For example, vegetarian", max_chars=200)
            allergies = st.text_input("Allergies or foods to avoid", value=profile["allergies"], placeholder="For example, peanuts", max_chars=200)
            if st.form_submit_button("Save preferences", type="primary", width="stretch"):
                save_settings({**profile, "name": name.strip(), "focus": focus, "preferences": preferences.strip(), "allergies": allergies.strip()})
                st.session_state.notice = "Your preferences have been saved."
                st.rerun()
        with st.expander("About FitPlate"):
            st.write("Meal chat, photo understanding, and voice transcription use Alibaba Cloud Model Studio. Text and selected media are sent to your configured service when you choose to process them.")
            st.write("Confirmed meals and settings are saved on this computer in a single-user local workspace.")
            st.write("Confirm food matches, portions and preparation before saving. Nutrition uses reference estimates; source verification varies by food. Weekly summaries use saved records only.")


def sidebar():
    with st.sidebar:
        st.html('<div class="brand">'+LOGO+'<span class="brand-name">FitPlate</span><span class="brand-dot">.</span></div><div class="brand-tag">EAT WITH INTENTION</div>')
        for page, label, icon in (
            ("Conversation", "Conversation", ":material/chat_bubble_outline:"),
            ("Meal records", "Meal records", ":material/calendar_today:"),
            ("Goals", "Goals & insights", ":material/donut_large:"),
        ):
            st.button(label, key=f"nav_{page}", icon=icon, type="primary" if st.session_state.page == page else "tertiary", width="stretch", on_click=navigate, args=(page,))
        with st.container(key="sidebar_today"):
            count = sum(meal["date"] == today().isoformat() for meal in list_meals())
            st.html('<div class="sidebar-today"><span>Today</span><strong>'+escape(tr('{0} meals saved').format(count))+'</strong></div>')
            st.button('View daily progress',key='sidebar_progress',icon=':material/arrow_outward:',type='tertiary',width='stretch',on_click=navigate,args=('Goals',))
        profile = read_settings()
        name = profile["name"] or "Your workspace"
        initial = name[0].upper()
        st.html(f'<div class="sidebar-bottom"><div class="avatar-row"><div class="avatar">{escape(initial)}</div><div>{escape(name)}<small>Local workspace</small></div></div></div>')


def header():
    st.session_state.mobile_route = st.session_state.page
    with st.container(key="mobile_nav"):
        st.html('<div class="brand">'+LOGO+'<span class="brand-name">FitPlate</span><span class="brand-dot">.</span></div>')
        st.selectbox("Navigate", ("Conversation", "Meal records", "Goals"), key="mobile_route", on_change=lambda: navigate(st.session_state.mobile_route), label_visibility="collapsed")
    formatted_date = today().strftime("%a, %d %b")
    if language() != 'en':
        day=today()
        weekday=('星期一','星期二','星期三','星期四','星期五','星期六','星期日')[day.weekday()]
        formatted_date=f'{day.year}年{day.month}月{day.day}日 · {weekday}'
    with st.container(key="workspace_toolbar"):
        left, right = st.columns([4, 1.4])
        with left:
            try:
                load_config()
                status = ""
            except ServiceError:
                status = "Manual entry available"
            status_badge = f'<span class="toolbar-status">{status}</span>' if status else ""
            st.html(f'<div class="toolbar-date">{formatted_date}{status_badge}</div>')
        with right:
            profile_editor()
    if st.session_state.notice:
        st.success(st.session_state.notice)
        st.session_state.notice = ""


def hero(eyebrow, heading, description):
    if language() != "en":
        heading = tr(heading)
    st.html(f'<div class="hero"><div class="eyebrow">{eyebrow}</div><h1>{heading}</h1><p>{description}</p></div>')


def draft_editor():
    draft = st.session_state.draft
    if draft is None:
        return
    seed_portion_estimates(draft)
    revision = st.session_state.draft_revision
    with st.container(key="draft"):
        st.markdown("#### Review your meal")
        st.caption("AI estimates are editable. Add details below or reply in chat; update the draft to refresh the estimate.")
        assessment = assess_meal(draft)
        if assessment['computed_count'] == assessment['total_count'] and assessment['computed_count']:
            draft.pop('estimation_notice',None)
        nutrition_panel(assessment)
        uncertainty_tools(draft)
        for caution in cautions_for(draft):
            st.warning(caution)
        if draft.get("estimation_notice"):
            st.info(draft["estimation_notice"])
        st.caption(current_notes(draft))
        if st.button("Estimate with AI", key="estimate_draft", icon=":material/auto_awesome:", type="tertiary"):
            if estimate_with_ai():
                st.rerun()
        if questions_for(draft):
            st.button("Use typical estimates", on_click=use_typical_estimates, key="typical_estimates", type="tertiary")
        with st.expander("Food matching options"):
            reference_source = st.selectbox("Search suggestions from", ("All sources", "USDA", "UK", "AU", "CA"), key="reference_source")
            st.caption("Filters the food-match suggestions below. Automatic matching uses the default reference; choose a specific match to use another source.")
        with st.form(f"meal_review_{revision}"):
            col_a, col_b = st.columns(2)
            with col_a:
                meal_date = st.date_input("Meal date", value=date.fromisoformat(draft["date"]), max_value=today(),key=f'meal_date_{revision}')
            with col_b:
                meal_types = ("Breakfast", "Lunch", "Dinner", "Snack")
                meal_type = st.selectbox("Meal", meal_types, index=meal_types.index(draft["meal_type"]),key=f'meal_type_{revision}')
            edited_items = []
            for index, item in enumerate(draft["items"]):
                a, b, c = st.columns([2, 1, 1])
                with a:
                    name = st.text_input(f"Food name {index + 1}", value=item["name"], key=f"food_{revision}_{index}", max_chars=100)
                with b:
                    quantity = st.number_input(f"Portion {index + 1}", min_value=0.0, max_value=100000.0, value=float(item["quantity"]) if item["quantity"] is not None else None, step=1.0, key=f"portion_{revision}_{index}", placeholder="Add amount")
                with c:
                    unit = st.selectbox(f"Unit {index + 1}", UNITS, index=UNITS.index(item["unit"]), key=f"unit_{revision}_{index}")
                with st.expander(f"Preparation & options: {item['name'] or 'Food ' + str(index + 1)}"):
                    prep = st.selectbox(f"Preparation {index + 1}", PREPARATIONS, index=PREPARATIONS.index(item["preparation"]), key=f"prep_{revision}_{index}")
                    candidates = reference_candidates(item["name"], prep, dataset=None if reference_source == "All sources" else reference_source) if item["name"] else []
                    ids = list(dict.fromkeys([c["food_id"] for c in candidates] + ([item["food_id"]] if item.get("food_id") in DEFAULT_DB.by_id else [])))
                    options = [None] + ids
                    selected_id = st.selectbox(f"Food match {index + 1}", options,
                        index=options.index(item.get("food_id")) if item.get("food_id") in options else 0,
                        format_func=lambda fid: "Automatic matching" if fid is None else DEFAULT_DB.by_id[fid].name,
                        key=f"match_{revision}_{index}")
                    confirmed = st.number_input(f"Confirmed weight (g) {index + 1}", min_value=0.0,
                        max_value=100000.0, value=float(item["confirmed_grams"]) if item.get("confirmed_grams") is not None else None, step=1.0,
                        key=f"grams_{revision}_{index}", placeholder="Optional: replace an uncertain unit conversion")
                    details = dict(item.get("details", {}))
                    cooking = cooking_editor(item, index, revision)
                    if cooking:
                        details['cooking'] = cooking
                    else:
                        details.pop('cooking', None)
                    source_item = {**item, 'details': details}
                    if selected_id is not None:
                        source_item['food_id'] = selected_id
                    source_rows = portions_for(source_item)
                    if source_rows and unit != 'g':
                        portion_ids = [None] + [r['id'] for r in source_rows]
                        prior_pid = details.get('source_portion_id')
                        chosen_pid = st.selectbox(f"Source portion {index + 1}", portion_ids,
                            index=portion_ids.index(prior_pid) if prior_pid in portion_ids else 0,
                            format_func=lambda pid: 'Use current portion estimate' if pid is None else f"{SOURCE_PORTIONS[pid]['description']} ({SOURCE_PORTIONS[pid]['grams']:g} g / {SOURCE_PORTIONS[pid]['amount']:g} measure; USDA {pid})",
                            key=f"source_portion_{revision}_{index}")
                        if chosen_pid:
                            details['source_portion_id'] = chosen_pid
                            st.caption('Portion means the number of the selected source measure. Reference weights are edible averages, not individual measurements.')
                        else:
                            details.pop('source_portion_id', None)
                    forms = ["Unknown", *portion_options(item)]
                    if len(forms) > 1 and item.get("unit") in {"piece", "serving"}:
                        prior_form = details.get("portion_form", "Unknown")
                        chosen_form = st.selectbox(f"Portion interpretation {index + 1}", forms,
                            index=forms.index(prior_form) if prior_form in forms else 0,
                            format_func=lambda form, assumed=details.get('estimated_portion_form', 'form not selected'): f"Automatic (assumed {assumed.lower()})" if form == "Unknown" else form,
                            key=f"portion_form_{revision}_{index}")
                        details["portion_form"] = chosen_form
                        if chosen_form != prior_form:
                            details.pop("estimated_grams", None)
                            details.pop("estimated_portion_form", None)
                    estimated_weight = st.number_input(f"Estimated total weight (g) {index + 1}", min_value=0.0, max_value=3000.0,
                        value=float(details["estimated_grams"]) if details.get("estimated_grams") else None, step=1.0,
                        key=f"estimated_g_{revision}_{index}", placeholder="Optional editable estimate, not a measured weight")
                    if estimated_weight:
                        if details.get("portion_form", "Unknown") == item.get("details", {}).get("portion_form", "Unknown"):
                            details["estimated_grams"] = estimated_weight
                        if estimated_weight != item.get("details", {}).get("estimated_grams"):
                            details["estimated_grams"] = estimated_weight
                            details["estimate_basis"] = "User-adjusted estimated total edible weight; not measured."
                    else:
                        details.pop("estimated_grams", None)
                    for detail_key, label in [("portion_size", "Portion size"), ("oil", "Added oil"), ("drained", "Drainage"),
                                              ("meat_fat", "Meat fat"), ("broth_consumed", "Broth consumed"),
                                              ("soup_contents", "Soup contents"), ("noodle_type", "Noodle type"), ("weight_basis", "Weight basis")]:
                        if detail_key not in detail_fields(item):
                            continue
                        choices = DETAIL_ENUMS[detail_key]
                        current = details.get(detail_key, choices[0])
                        details[detail_key] = st.selectbox(f"{label} {index + 1}", choices, index=choices.index(current), key=f"{detail_key}_{revision}_{index}")
                    oil_grams = details.get("oil_grams")
                    if "oil" in detail_fields(item):
                        oil_grams = st.number_input(f"Oil eaten in this portion (g) {index + 1}", min_value=0.0, max_value=3000.0,
                            value=float(details["oil_grams"]) if details.get("oil_grams") is not None else None, step=1.0, key=f"oil_g_{revision}_{index}", placeholder="Optional; not the whole pan")
                    if details.get("oil") == "None":
                        details["oil_grams"] = 0
                    elif oil_grams is not None:
                        details["oil_grams"] = oil_grams
                    else:
                        details.pop("oil_grams", None)
                    remove = st.checkbox(f"Remove food {index + 1}", key=f"remove_{revision}_{index}")
                if not remove:
                    if name.strip() != item["name"]:
                        for field in ("recipe_key", "ai_components", "reference_food_id", "estimated_grams", "estimate_basis", "source_portion_id"):
                            details.pop(field, None)
                    if (quantity != item["quantity"] or unit != item["unit"]) and quantity is not None:
                        details["quantity_origin"] = "User"
                        details.pop("estimated_grams", None)
                    previous_details = item.get("details", {})
                    if prep != item["preparation"] or any(
                            details.get(k, DETAIL_ENUMS[k][0] if k in DETAIL_ENUMS else None) !=
                            previous_details.get(k, DETAIL_ENUMS[k][0] if k in DETAIL_ENUMS else None) for k in
                            ("oil", "oil_grams", "drained", "meat_fat", "broth_consumed", "soup_contents", "noodle_type", "weight_basis")):
                        details.pop("ai_components", None)
                        details.pop("reference_food_id", None)
                    if (details.get("portion_size", "Unknown") != previous_details.get("portion_size", "Unknown")
                            and estimated_weight == previous_details.get("estimated_grams")):
                        details.pop("estimated_grams", None)
                    edited_item = {"name": name.strip(), "quantity": quantity, "unit": unit, "preparation": prep, "details": details}
                    if name.strip() == item["name"] and selected_id is not None:
                        edited_item["food_id"] = selected_id
                    portion_changed = name.strip() != item["name"] or quantity != item["quantity"] or unit != item["unit"]
                    if confirmed is not None and not (portion_changed and confirmed == item.get("confirmed_grams")):
                        edited_item["confirmed_grams"] = confirmed
                    edited_items.append(edited_item)
            note = st.text_input("Meal notes", value=clean_notes(draft.get("note", "")), placeholder="Oil, sauce, brand, or anything to remember", max_chars=500,key=f'meal_note_{revision}')
            review_estimates = st.checkbox("I reviewed the estimated portions and recipe assumptions", key=f"estimate_review_{revision}")
            left, right = st.columns(2)
            with left:
                save_clicked = st.form_submit_button("Save meal", type="primary", icon=":material/check:", width="stretch")
            with right:
                update_clicked = st.form_submit_button("Update draft", width="stretch")
            if save_clicked or update_clicked:
                edited = {**draft, "date": meal_date.isoformat(), "meal_type": meal_type, "items": edited_items, "note": clean_notes(note), "estimate_reviewed": review_estimates}
                seed_portion_estimates(edited)
                st.session_state.draft = edited
                if save_clicked:
                    updated_assessment = assess_meal(edited)
                    error = validate_draft(edited)
                    if updated_assessment.get("estimation_errors"):
                        error = updated_assessment["estimation_errors"][0]
                    if updated_assessment['computed_count'] == 0:
                        error = 'No nutrition could be calculated. Use Estimate with AI or choose food matches and portions before saving.'
                    if updated_assessment["requires_estimate_review"] and not review_estimates:
                        error = "Review and accept the recipe/portion estimates, or replace them with confirmed details."
                    if error:
                        st.error(error)
                    else:
                        save_meal(edited)
                        advance_draft()
                        st.session_state.draft_revision += 1
                        assistant(f"{meal_type} saved. Find or edit it in Meal records.")
                        st.session_state.notice = "Meal saved to your local records."
                        st.rerun()
                else:
                    st.session_state.draft_revision += 1
                    st.session_state.notice = "Draft updated. It has not been saved as a meal."
                    st.rerun()
        a, b = st.columns(2)
        with a:
            st.button("Add a custom food", key="draft_add", icon=":material/add:", on_click=new_custom, width="stretch")
        with b:
            if st.button("Discard draft", key="discard_draft", width="stretch"):
                advance_draft()
                st.session_state.draft_revision += 1
                assistant("Draft discarded. Your saved meals are unchanged.")
                st.rerun()


def process_media(media):
    """Process only an explicit submission or retry, never a normal rerun."""
    data, name, text = media["data"], media["name"], media["text"]
    suffix = Path(name).suffix.lower()
    source = media.get("source") or ("Voice" if suffix in AUDIO_SUFFIXES else "Photo")
    digest = hashlib.sha256(source.encode() + data).hexdigest()
    st.session_state.ai_error = ""
    if source == "Photo":
        try:
            data = normalize_photo(data)
        except PhotoError as error:
            st.session_state.ai_error = str(error)
            return False
        if st.session_state.draft is not None:
            st.session_state.ai_error = "Finish or discard your current draft before sending a new meal photo. Your attachment is kept below."
            return False
        if receive(text or "Identify the foods in this meal photo. Ask me to confirm the foods and portions.", image=data, source="Photo"):
            message = next(m for m in reversed(st.session_state.messages) if m["role"] == "user")
            with Image.open(io.BytesIO(data)) as preview:
                preview = preview.convert("RGB")
                preview.thumbnail((480, 480))
                buffer = io.BytesIO()
                preview.save(buffer, "JPEG", quality=80)
                message["image"] = buffer.getvalue()
            st.session_state.attachment = {"source": source, "name": name, "digest": digest}
            st.session_state.voice_ready = None
            return True
        return False
    try:
        if digest not in st.session_state.transcripts:
            with st.spinner("Transcribing your meal note..."):
                st.session_state.transcripts[digest] = agent.transcribe(data, name)
        transcript = st.session_state.transcripts[digest]
        combined = "\n\n".join(part for part in (text.strip(), transcript) if part)
        if len(combined) > 4000:
            raise ServiceError("The recording and note are too long. Please use a shorter recording.")
        st.session_state.voice_ready = {"name": name, "data": data, "digest": digest}
        st.session_state.composer_prefill = combined
        return True
    except ServiceError as error:
        st.session_state.ai_error = str(error)
        return False


def submit_message(submission):
    text = submission if isinstance(submission, str) else submission.text
    files = [] if isinstance(submission, str) else (submission.get("files") or [])
    recording = None if isinstance(submission, str) else submission.get("audio")
    uploads = list(files) + ([recording] if recording is not None else [])
    st.session_state.ai_error = ""
    if len(uploads) > 1:
        st.session_state.ai_error = "Please send one photo or one recording at a time. Reattach the file you want to use."
        st.session_state.composer_prefill = text
        return
    if uploads:
        upload = uploads[0]
        data = upload.getvalue()
        if not data or len(data) > MAX_PHOTO_BYTES:
            st.session_state.ai_error = "Choose an attachment smaller than 20 MB."
            st.session_state.composer_prefill = text
            return
        media = {"name": upload.name, "data": data, "text": text, "source": "Voice" if recording is not None else ("Voice" if Path(upload.name).suffix.lower() in AUDIO_SUFFIXES else "Photo")}
        st.session_state.pending_media = media
        if process_media(media):
            st.session_state.pending_media = None
        return
    if text.strip():
        source = "Voice" if st.session_state.voice_ready else "Text"
        if receive(text, source=source):
            st.session_state.voice_ready = None
        else:
            st.session_state.composer_prefill = text


def composer():
    with st.container(key="unified_composer"):
        pending = st.session_state.pending_media
        if pending:
            st.caption(f"Attachment kept: {pending['name']}")
            a, b = st.columns(2)
            with a:
                if st.button("Retry attachment", width="stretch"):
                    if process_media(pending):
                        st.session_state.pending_media = None
                    st.rerun()
            with b:
                if st.button("Remove attachment", width="stretch"):
                    st.session_state.composer_prefill = pending["text"]
                    st.session_state.pending_media = None
                    st.session_state.ai_error = ""
                    st.rerun()
        voice = st.session_state.voice_ready
        if voice:
            with st.expander("Voice note · transcript ready", expanded=False):
                st.audio(voice["data"])
                st.caption("Your transcript is in the message box. Check names, numbers, and units, then send.")
                if st.button("Remove voice note", type="tertiary"):
                    st.session_state.voice_ready = None
                    st.rerun()
        if st.session_state.composer_prefill is not None:
            st.session_state.meal_composer = st.session_state.composer_prefill
            st.session_state.composer_prefill = None
        submission = st.chat_input(
            "Describe a meal, attach a photo, or record a note...", key="meal_composer",
            accept_file=True, file_type=None,
            accept_audio=False, max_chars=4000, max_upload_size=20,
            submit_mode="disable", disabled=pending is not None,
        )
        if pending is None:
            voice_input(process_media)
        if submission is not None:
            submit_message(submission)
            st.rerun()


def conversation():
    hero("", "What was on <em>your plate?</em>", "A sentence is enough to get started.")
    if missing_fields(read_body_profile()) and not st.session_state.messages:
        st.button('Set up personal coaching',icon=':material/person:',on_click=open_body_profile)
    with st.container(key="conversation"):
        with st.container(height=400, border=False, key="message_history", autoscroll=True):
            if not st.session_state.messages:
                st.html('<div class="chat-welcome">'+LOGO+'<p>Tell me what you ate and any portions you know.</p></div>')
                with st.container(key="chat_starters"):
                    for index,(col,label,prompt,icon) in enumerate(zip(st.columns(3),
                            ('Describe a meal','Review my day','Plan my next meal'),
                            ('For lunch I had chicken breast, rice and broccoli.','Review my day','Help me plan my next meal based on my goals and what I have eaten today.'),
                            (':material/restaurant:',':material/analytics:',':material/auto_awesome:'))):
                        with col:
                            st.button(label,key=f'chat_starter_{index}',icon=icon,width='stretch',on_click=prefill_message,args=(prompt,))
            for message in st.session_state.messages:
                role = "You" if message["role"] == "user" else "FitPlate"
                user_class = " user" if message["role"] == "user" else ""
                st.html(f'<div class="chat-name">{role}</div>')
                if message['role']=='user':st.html(f'<div class="bubble user">{escape(message["text"])}</div>')
                else:
                    displayed=tr(message['text'])
                    if language()!='en' and has_english_prose(displayed):
                        st.caption('This earlier reply uses another language. Ask again to receive a reply in your selected language.')
                        with st.expander('Earlier reply (original language)'):native_st.markdown(message['text'])
                    else:st.markdown(displayed)
                if message.get('tool_trace') or message.get('sources'):
                    with st.expander('Information used for this reply'):
                        for tool in message.get('tool_trace',[]):st.caption(tool['label'])
                        for source in message.get('sources',[]):st.markdown(f"[{source['title']}]({source['url']})")
                if message.get("image"):
                    st.image(message["image"], width=180)
        composer()
    photo_tools()
    if st.session_state.ai_error:
        st.error(st.session_state.ai_error)
    st.html('<div class="fine-print compact-notice">AI suggests. You confirm. Nutrition values are reference-based estimates.</div>')
    workspace=combine_drafts(st.session_state.draft,st.session_state.draft_queue,[])
    if len(workspace)>1:
        st.caption(f'Pending drafts: {len(workspace)}')
        st.session_state.active_meal_draft=st.session_state.draft['id']
        labels={d['id']:tr(d['meal_type'])+' · '+d['date'] for d in workspace}
        st.selectbox('Edit meal draft',list(labels),format_func=lambda key:labels[key],key='active_meal_draft',on_change=select_draft)
        st.caption('Use Update draft to keep field edits before switching meals. Save meal saves only the selected draft.')
    draft_editor()
    with st.expander("Examples & more"):
        a, b = st.columns(2)
        with a:
            if st.button("Try a lunch example", icon=":material/restaurant:", width="stretch"):
                receive("For lunch I had chicken breast, rice and broccoli.")
                st.rerun()
        with b:
            if st.button("Review my day", icon=":material/wb_sunny:", width="stretch"):
                receive("Review my day")
                st.rerun()
        if st.session_state.draft is None:
            st.button("Add food manually", icon=":material/add:", on_click=new_custom, type="tertiary")
        if st.session_state.messages:
            if st.button("Clear conversation", type="tertiary", icon=":material/restart_alt:"):
                st.session_state.messages = []
                st.session_state.seen_uploads = []
                st.session_state.transcripts = {}
                st.session_state.attachment = None
                st.session_state.upload_revision += 1
                st.session_state.ai_error = ""
                st.session_state.pending_media = None
                st.session_state.voice_ready = None
                st.session_state.composer_prefill = None
                st.rerun()


def records():
    hero("", "Your <em>meal records.</em>", "Review, edit, or repeat a meal.")
    meals = sorted(list_meals(), key=lambda meal: meal['date'], reverse=True)
    transfer_controls(meals)
    if not meals:
        st.html('<div class="empty-state"><div style="font-size:29px;color:#7c9965">&#9673;</div><h3>Your first plate belongs here.</h3><p>Start a conversation, review the details, and save your first meal.</p></div>')
        st.button("Log your first meal", icon=":material/add:", type="primary", on_click=navigate, args=("Conversation",))
        return
    a, b = st.columns(2)
    with a:
        selected_type = st.selectbox("Meal type", ("All meals", "Breakfast", "Lunch", "Dinner", "Snack"), key="record_meal_type")
    with b:
        search = st.text_input("Search foods", placeholder="For example, rice", key="record_search")
    def matches_search(meal):
        names=[tr(item['name'],locale) for item in meal['items'] for locale in LANGUAGES]
        return search.casefold() in (json.dumps(meal['items'],ensure_ascii=False)+' '+' '.join(names)).casefold()
    visible = [m for m in meals if (selected_type == "All meals" or m["meal_type"] == selected_type) and matches_search(m)]
    st.caption(f"{len(visible)} record(s) shown. Nutrition uses saved reference estimates; older records may be uncalculated.")
    for meal in visible:
        food_text = " | ".join(f"{str(i['quantity']) + ' ' + tr(i['unit']) if i['quantity'] is not None else tr('Estimated portion of')} {tr(i['name'])} ({tr(i['preparation'])})" for i in meal["items"])
        st.html(f'<div class="record-card"><h3>{escape(meal["meal_type"])} <span style="font-weight:400;color:#91a080;font-size:12px"> / {escape(meal["date"])}</span></h3><p>{escape(food_text)}</p><p>{escape(clean_notes(meal.get("note", "")))}</p><span class="local-pill">Saved meal</span></div>')
        stored_nutrition = snapshot(meal)
        if meal.get('import_info'):
            st.caption('Imported record. Saved nutrition values are preserved as provided; importing does not independently verify or recalculate them.')
        preview = None
        if not meal.get('import_info') and (not stored_nutrition or stored_nutrition["completeness"] != "complete"):
            candidate = assess_meal({**meal, 'estimate_reviewed': False})
            if candidate["computed_count"] > (stored_nutrition["computed_count"] if stored_nutrition else 0):
                preview = candidate
                st.caption("New estimate preview — your saved record and daily totals stay unchanged until you review and save it.")
        nutrition_panel(preview or stored_nutrition)
        st.caption(current_notes(meal))
        a, b, c = st.columns(3)
        with a:
            if st.button("Review estimate" if preview else "Edit meal", key=f"edit_{meal['id']}", icon=":material/edit:", width="stretch"):
                if st.session_state.draft is not None and st.session_state.draft.get("id") != meal["id"]:
                    st.error("Finish or discard your current draft before editing another meal.")
                    continue
                st.session_state.draft = {key: value for key, value in meal.items() if key != "nutrition"}
                st.session_state.draft["estimate_reviewed"] = False
                st.session_state.draft_revision += 1
                navigate("Conversation")
                st.rerun()
        with b:
            if st.button("Reanalyse with AI", key=f"estimate_{meal['id']}", icon=":material/auto_awesome:", width="stretch"):
                if estimate_with_ai(meal):
                    st.rerun()
        with c:
            with st.popover("Delete meal", icon=":material/delete_outline:", width="stretch"):
                st.write("Delete this meal from local records? This action cannot be undone.")
                if st.button("Confirm delete", key=f"delete_{meal['id']}"):
                    delete_meal(meal["id"])
                    st.session_state.notice = "Meal deleted."
                    st.rerun()



def goals():
    hero("", "Nutrition goals & review", "Set your targets and explore your eating patterns.")
    body_profile_editor()
    if st.button('Analyse meals & goals',icon=':material/analytics:'):
        receive(tr('Review my saved nutrition targets and the meals available in drafts or records. Explain what is known, what is missing, and one practical next step. Do not treat unlogged food as zero intake.'))
        navigate('Conversation')
        st.rerun()
    if st.button('Ask for a diet & training suggestion',icon=':material/chat_bubble_outline:'):
        receive(tr('Based on the profile I chose to share and my saved meals, suggest one practical diet adjustment and a realistic training next step. Ask for missing details if needed.'))
        navigate('Conversation')
        st.rerun()
    profile = read_settings()
    grid = '<div class="metric-grid">'
    for key, label, unit in (("energy", "Energy", "kcal"), ("protein", "Protein", "g"), ("carbs", "Carbohydrates", "g"), ("fat", "Fat", "g")):
        value = f"{profile[key]:g}" if profile[key] is not None else "--"
        grid += f'<div class="metric"><small>{label}</small><b>{value} <span>{unit}</span></b><span>Daily target</span></div>'
    if any(profile[key] is not None for key in ("energy", "protein", "carbs", "fat")):
        st.html(grid + "</div>")
    with st.container(key="goals_form"):
        st.markdown("#### Set your daily targets")
        st.caption("Enter targets from your own plan. No target is generated or prescribed in this preview.")
        with st.form("targets"):
            a, b = st.columns(2)
            with a:
                energy = st.number_input("Energy target (kcal)", min_value=0.0, max_value=100000.0, value=float(profile["energy"]) if profile["energy"] is not None else None, step=50.0, placeholder="Optional")
                protein = st.number_input("Protein target (g)", min_value=0.0, max_value=10000.0, value=float(profile["protein"]) if profile["protein"] is not None else None, step=5.0, placeholder="Optional")
            with b:
                carbs = st.number_input("Carbohydrate target (g)", min_value=0.0, max_value=10000.0, value=float(profile["carbs"]) if profile["carbs"] is not None else None, step=5.0, placeholder="Optional")
                fat = st.number_input("Fat target (g)", min_value=0.0, max_value=10000.0, value=float(profile["fat"]) if profile["fat"] is not None else None, step=5.0, placeholder="Optional")
            if st.form_submit_button("Save targets", type="primary", icon=":material/check:"):
                values = dict(energy=energy, protein=protein, carbs=carbs, fat=fat)
                if any(value is not None and value <= 0 for value in values.values()):
                    st.error("Use positive targets, or leave a field empty.")
                else:
                    save_settings({**profile, **values})
                    st.session_state.notice = "Your targets have been saved."
                    st.rerun()
    st.markdown("#### Today’s calculated intake")
    summary = daily_summary(list_meals(), today().isoformat())
    definitions = summary.get("carb_definitions")
    if definitions is None:
        summary = {**summary, "totals": {**summary["totals"], "carbs": None}}
    cols = st.columns(4)
    for col, key, label, unit in zip(cols, ("energy", "protein", "carbs", "fat"), ("Energy", "Protein", "Carbs", "Fat"), ("kcal", "g", "g", "g")):
        value, target = summary["totals"][key], profile[key]
        col.metric(label, "—" if value is None else f"{value:g} {unit}")
        if target and value is not None:
            col.progress(min(value / target, 1.0), text=f"{value / target:.0%} of your target")
    st.caption(f"{summary['meal_count']} meal(s) saved; {summary['incomplete_meals']} meal(s) have missing or incomplete nutrition. Totals include calculated items only and are estimates.")
    if len(definitions or []) > 1:
        st.caption("Carbohydrates use different source definitions, so a combined carbohydrate total is not shown.")
    elif definitions is None and summary["computed_items"]:
        st.caption("Carbohydrate comparison is unavailable for this summary.")
    if summary.get("estimated_meals"):
        bounds = summary.get("energy_scenario_range")
        st.caption(f"{summary['estimated_meals']} meal(s) include reviewed recipe/portion estimates. " +
                   (f"Energy scenario range: {bounds[0]:.0f}–{bounds[1]:.0f} kcal; not a confidence interval." if bounds else ""))
    def request_weekly_review(prompt):
        receive(prompt)
        navigate('Conversation')
        st.rerun()
    weekly_review(list_meals(),profile,request_weekly_review)


from fitplate.visitors import ensure_visitor
ensure_visitor()
initialize()
st.set_page_config(page_title=tr('FitPlate | Eat with intention'))
sidebar()
header()
if st.session_state.page == "Conversation":
    conversation()
elif st.session_state.page == "Meal records":
    records()
else:
    goals()
st.html('<div class="page-footer"><span>FITPLATE</span><span>Your meals, at your pace.</span></div>')
localize_framework_controls()

