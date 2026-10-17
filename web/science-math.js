// Only base/AMS TeX is enabled; imported HTML cannot load extensions or links.
window.MathJax={tex:{packages:['base','ams'],inlineMath:[['\\(','\\)']],displayMath:[['\\[','\\]']],maxBuffer:20000},options:{enableMenu:false},startup:{ready(){MathJax.startup.defaultReady();MathJax.startup.promise.then(()=>window.dispatchEvent(new Event('science-math-ready')))}}};
const mathScript=document.createElement('script');mathScript.src='https://cdn.jsdelivr.net/npm/mathjax@3.2.2/es5/tex-svg.js';mathScript.async=true;document.head.append(mathScript);
