"""Anonymous browser workspaces; no account or user-supplied API key."""
from contextvars import ContextVar
import hashlib
import hmac
import os
from pathlib import Path
import re
import secrets
import threading

_identity = ContextVar('fitplate_visitor', default=None)
_key_lock = threading.Lock()


def data_root():
    return Path(os.environ.get('FITPLATE_DATA_DIR') or Path(__file__).resolve().parents[1] / 'data')


def signing_key():
    path = data_root() / '.visitor_key'
    with _key_lock:
        path.parent.mkdir(parents=True, exist_ok=True)
        if not path.exists():
            try:
                with path.open('xb') as f:
                    f.write(secrets.token_bytes(32))
                if os.name != 'nt':
                    path.chmod(0o600)
            except FileExistsError:
                pass
        key = path.read_bytes()
    if len(key) != 32:
        raise RuntimeError('The workspace signing key is invalid. Contact the administrator.')
    return key


def create_token():
    identifier = secrets.token_hex(16)
    return identifier + '.' + hmac.new(signing_key(), identifier.encode(), hashlib.sha256).hexdigest()


def validate_token(token):
    if not isinstance(token, str) or not re.fullmatch(r'[a-f0-9]{32}\.[a-f0-9]{64}', token):
        return None
    identifier, signature = token.split('.')
    expected = hmac.new(signing_key(), identifier.encode(), hashlib.sha256).hexdigest()
    return identifier if hmac.compare_digest(signature, expected) else None


def activate(token):
    identifier = validate_token(token)
    if not identifier:
        raise ValueError('Invalid visitor identity')
    _identity.set(identifier)
    return identifier


def current_visitor():
    return _identity.get()


def workspace_directory():
    identifier = current_visitor()
    return data_root() / 'visitors' / identifier if identifier else data_root()


def ensure_visitor():
    import streamlit as st
    from fitplate.i18n import tr
    from fitplate.visitor_component import visitor_component
    state = st.session_state
    if '_visitor_proposal' not in state:
        state['_visitor_proposal'] = create_token()
    result = visitor_component(data={'proposal': state['_visitor_proposal']}, key='visitor_identity', on_identity_change=lambda: None)
    identity = result.identity
    if identity is None:
        token = state.get('_visitor_token')
        if token and validate_token(token):
            activate(token)
            return
        st.caption(tr('Opening your private workspace...'))
        st.stop()
    if not isinstance(identity, dict) or not validate_token(identity.get('token')):
        st.error(tr("Your browser workspace could not be verified. Clear this site's browser storage and reload."))
        st.stop()
    token = identity['token']
    if state.get('_visitor_token') not in (None, token):
        # Do not carry a previous visitor's draft, body profile or widgets across identities.
        for key in list(state):
            if key not in ('visitor_identity', '_visitor_proposal'):
                del state[key]
        st.rerun()
    state['_visitor_token'] = token
    activate(token)
    if identity.get('persistent') is not True:
        st.info(tr('Browser storage is unavailable. Export your meals before closing this page; this workspace will not reopen automatically.'))
