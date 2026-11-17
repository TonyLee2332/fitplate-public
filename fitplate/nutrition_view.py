"""Compact nutrition display shared by drafts and records."""
from fitplate.ui import st


def nutrition_panel(result):
    if result is None:
        st.caption("Not calculated — edit and save this meal to calculate nutrition.")
        return
    st.caption(f"{result['nutrition_status']} · {result['computed_count']}/{result['total_count']} foods calculated")
    cols = st.columns(4)
    for col, (key, label, unit) in zip(cols, [("energy", "Energy", "kcal"), ("protein", "Protein", "g"),
                                           ("carbs", "Carbs", "g"), ("fat", "Fat", "g")]):
        value = result["totals"][key]
        estimated = bool(result.get("requires_estimate_review"))
        col.metric(label, "—" if value is None else f"≈ {value:.0f} {unit}" if estimated else f"{value:g} {unit}")
        bounds = result.get("scenario_range", {}).get(key)
        if bounds and bounds[0] != bounds[1]:
            col.caption(f"Scenario: {bounds[0]:.0f}–{bounds[1]:.0f} {unit}")
    if result.get("requires_estimate_review"):
        st.caption("Scenario ranges reflect portion/recipe assumptions, not statistical confidence intervals. " +
                   ("Assumptions reviewed." if result.get("estimate_reviewed") else "Review the assumptions before saving."))
    for item in result['items']:
        for assumption in item.get('assumptions',[]):
            if 'conflicts with the earlier' in assumption:
                st.warning(assumption)
    if result["completeness"] != "complete":
        st.caption("Partial totals include calculated foods only; missing foods are not zero intake.")
    if any("Carbohydrate definitions differ" in w for w in result["warnings"]):
        st.caption("Carbohydrate definitions differ across these sources; the carbohydrate total is unavailable.")
    for pending in result["pending_items"]:
        st.caption(f"Food {pending['input_index'] + 1}: {pending['reason']}")
    sampling = result.get('uncertainty_analysis')
    if sampling:
        with st.expander('Sampled scenarios & sensitivity'):
            st.caption(f"{sampling['samples']} seeded scenarios; modelled percentiles, not calibrated confidence intervals.")
            st.dataframe([dict(nutrient=k,**v) for k,v in sampling['statistics'].items() if v],hide_index=True)
            if sampling['drivers']:
                st.dataframe(sampling['drivers'][:8],hide_index=True)
            for assumption in sampling['assumptions']:
                st.caption(assumption)
    with st.expander("Estimates & food sources"):
        for item in result["items"]:
            if item.get('cooking_source'):
                st.caption('FAO recipe mass-balance calculation; ingredient weights refer to their selected source state.')
                st.markdown(f"[Recipe calculation method]({item['cooking_source']['method']})")
            portion = item.get('portion_source')
            if portion:
                st.caption(f"USDA source portion {portion['id']}: {portion['description']} · {portion['calculated_grams']:g} g calculated")
                st.markdown(f"[Original portion dataset]({portion['source_url']})")
            for assumption in item.get("assumptions", []):
                st.caption(f"{item.get('input_name', item['name'])}: {assumption}")
            source = item.get("source")
            if source:
                st.write(f"{item['name']} · {source['verification']}")
                st.caption(f"{source['source']} · {source['source_version']}")
                if source.get("source_ref"):
                    st.markdown(f"[Source / comparison]({source['source_ref']})")
                st.caption(source.get("verification_note", ""))
                st.caption(f"Carbohydrates: {source.get('carb_definition') or 'Definition not recorded'}")
            if item.get("match_type") == "recipe":
                st.caption("Modelled reference equivalents; these are not confirmed actual ingredients unless you supplied them.")
                for component in item.get("components", []):
                    ref = component.get("source") or {}
                    st.caption(f"{component.get('quantity') or 0:g} g · {component['name']}")
                    if ref.get("source_ref"):
                        st.markdown(f"[Ingredient reference]({ref['source_ref']})")
        for message in result["warnings"]:
            st.caption(message)
