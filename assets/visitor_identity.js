export default function(component) {
    const {data, setStateValue} = component;
    const key = 'fitplate.visitor.v1';
    let token = data.proposal;
    let persistent = false;
    try {
        const saved = localStorage.getItem(key);
        if (saved && /^[a-f0-9]{32}\.[a-f0-9]{64}$/.test(saved)) token = saved;
        localStorage.setItem(key, token);
        persistent = localStorage.getItem(key) === token;
    } catch (_) {
        // Private storage restrictions retain a session-only workspace.
    }
    setStateValue('identity', {token, persistent});
}
