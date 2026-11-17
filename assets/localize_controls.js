(() => {
  const config = __FITPLATE_LOCALE__;
  window.fitplateControlLocale?.disconnect();
  document.documentElement.lang = config.language;
  const translations = config.translations;
  const reverse = config.reverse;
  const translate = value => translations[reverse[value] || value] || value;
  const apply = () => {
    for (const element of document.querySelectorAll('[aria-label], [title]')) {
      for (const attribute of ['aria-label', 'title']) {
        const original = element.getAttribute(attribute);
        const translated = translate(original);
        if (original && translated !== original) element.setAttribute(attribute, translated);
      }
    }
    // Only framework media controls are eligible; never rewrite user messages or inputs.
    for (const root of document.querySelectorAll('[data-testid="stChatInput"], [data-testid="stFileUploader"], [data-testid="stAudioInput"]')) {
      const walker = document.createTreeWalker(root, NodeFilter.SHOW_TEXT);
      let node;
      while ((node = walker.nextNode())) {
        if (['TEXTAREA', 'SCRIPT', 'STYLE'].includes(node.parentElement?.tagName)) continue;
        const text = node.textContent.trim();
        const translated = translate(text);
        if (translated !== text) node.textContent = node.textContent.replace(text, translated);
      }
    }
  };
  let scheduled = false;
  const observer = new MutationObserver(() => {
    if (!scheduled) {
      scheduled = true;
      requestAnimationFrame(() => { scheduled = false; apply(); });
    }
  });
  observer.observe(document.body, {subtree: true, childList: true, attributes: true, attributeFilter: ['aria-label', 'title']});
  window.fitplateControlLocale = observer;
  apply();
})();
