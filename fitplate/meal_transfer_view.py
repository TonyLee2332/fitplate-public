"""Compact, local-only meal import/export controls."""
import sqlite3
from fitplate.ui import st
from fitplate.i18n import tr
from fitplate.meal_transfer import TransferError, export_csv, export_json, parse_import, import_meals


def transfer_controls(meals):
    with st.expander('Import & export', icon=':material/import_export:'):
        if meals:
            left, right = st.columns(2)
            with left:
                st.download_button('Export meal details', data=export_csv(meals), file_name='fitplate_meals.csv', mime='text/csv', icon=':material/download:', width='stretch')
            with right:
                st.download_button('Export complete backup', data=export_json(meals), file_name='fitplate_meals_backup.json', mime='application/json', icon=':material/backup:', width='stretch')
        st.caption('Import a FitPlate CSV export or JSON backup. New exports preserve complete meal details and saved nutrition results. Existing meal IDs are skipped.')
        uploaded = st.file_uploader('Import meal history', type=['csv', 'json'], max_upload_size=10, key='meal_history_upload')
        if uploaded is None:
            return
        try:
            batch = parse_import(uploaded.getvalue(), uploaded.name)
        except TransferError as error:
            st.error(str(error))
            st.caption('Nothing was imported. Your existing records are unchanged.')
            return
        existing = {meal['id'] for meal in meals}
        skipped = sum(meal['id'] in existing for meal in batch['meals'])
        additions = len(batch['meals']) - skipped
        st.caption(tr('{0} meals found; {1} new; {2} existing IDs will be skipped.').format(len(batch['meals']), additions, skipped))
        st.dataframe([{'Date': m['date'], 'Meal type': m['meal_type'], 'Foods': len(m['items']),
                       'Nutrition': (m.get('nutrition') or {}).get('nutrition_status', 'Not calculated'),
                       'Import action': 'Skip existing' if m['id'] in existing else 'Add new'} for m in batch['meals'][:20]], hide_index=True)
        if len(batch['meals']) > 20:
            st.caption('The preview shows the first 20 meals. All validated meals will be processed.')
        if batch['legacy']:
            st.info('This older CSV contains fewer details. Available foods, portions, nutrients and sources will be preserved; missing values will remain unknown.')
        if st.button('Import new meals', type='primary', icon=':material/upload:', disabled=additions == 0, key='confirm_meal_import'):
            try:
                result = import_meals(batch)
            except (TransferError, sqlite3.Error):
                st.error('The import could not be completed. No meals were added; check the file and try again.')
                return
            st.session_state.record_meal_type = 'All meals'
            st.session_state.record_search = ''
            st.session_state.notice = tr('Imported {0} meals; skipped {1} existing IDs.').format(result['imported'], result['skipped'])
            st.rerun()
