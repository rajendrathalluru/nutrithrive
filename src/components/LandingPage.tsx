import React, { useEffect, useRef, useState } from 'react';
import { ArrowRight, ArrowUpRight, Check, ChevronDown, Clock3, CookingPot, ExternalLink, Leaf, LogOut, Menu, MessageCircle, Package, SlidersHorizontal, Sparkles, Sprout, X } from 'lucide-react';
import homeMeal from '../assets/images/home-meal.jpg';
import './LandingPage.css';

interface LandingPageProps {
  onGetStarted?: () => void;
  onLogout?: () => void;
}

const navigation = [
  { label: 'How it works', href: '#how-it-works' },
  { label: 'Recipe inspiration', href: '#recipes' },
  { label: 'Our approach', href: '#approach' },
];

const steps = [
  { title: 'Tell us what works for you.', description: 'A favorite cuisine, ingredients on hand, or a little less time in the kitchen. Start in your own words.', icon: MessageCircle },
  { title: 'Explore a few possibilities.', description: 'Get up to three recipe ideas at a time, with ingredients, instructions, and clear source labels.', icon: CookingPot },
  { title: 'Make it a conversation.', description: 'Ask for more ideas or refine your preferences. Follow-ups build on the conversation in your current chat.', icon: SlidersHorizontal },
];

const inspirations = [
  { title: 'A little less effort', label: 'QUICK & SIMPLE', prompt: '“What can I make in under 30 minutes?”', icon: Clock3, tone: 'sand' },
  { title: 'More plants on your plate', label: 'PLANT-FORWARD', prompt: '“Show me some vegetarian dinner ideas.”', icon: Sprout, tone: 'sage' },
  { title: 'Start with your pantry', label: 'USE WHAT YOU HAVE', prompt: '“What meals can I make with canned beans?”', icon: Package, tone: 'peach' },
];

const questions = [
  { question: 'Where do the recipes come from?', answer: 'Thrivewell looks for matching recipes in its database first, including recipes from AICR, ACS, and AHA. If a suitable match is not available, it can create a recipe using AI. Database recipes include their source links, and new AI-created recipes are labeled AI Generated.' },
  { question: 'Can I ask follow-up questions?', answer: 'Yes. Ask for more recipes, refine an ingredient preference, or refer to a recipe already shown. Each chat keeps its own context while the app is open. Conversations are not currently saved across page refreshes.' },
  { question: 'Does Thrivewell replace advice from my care team?', answer: 'No. Thrivewell offers recipe ideas, not diagnosis or medical treatment. Follow the dietary guidance from your care team. Keep prompts focused on food preferences and avoid sharing personal or identifying health information.' },
];

const LandingPage: React.FC<LandingPageProps> = ({ onGetStarted, onLogout }) => {
  const [menuOpen, setMenuOpen] = useState(false);
  const menuButtonRef = useRef<HTMLButtonElement>(null);

  useEffect(() => {
    if (!menuOpen) return;
    const closeOnEscape = (event: KeyboardEvent) => {
      if (event.key !== 'Escape') return;
      setMenuOpen(false);
      menuButtonRef.current?.focus();
    };
    window.addEventListener('keydown', closeOnEscape);
    return () => window.removeEventListener('keydown', closeOnEscape);
  }, [menuOpen]);

  const startChat = () => {
    setMenuOpen(false);
    onGetStarted?.();
  };

  return (
    <div className="thrive-home" id="home-top">
      <a className="home-skip-link" href="#home-main">Skip to content</a>
      <header className="home-header">
        <div className="home-header-inner home-container">
          <a className="home-brand" href="#home-top" aria-label="Thrivewell home">
            <Leaf aria-hidden="true" /><span>Thrivewell<span className="home-brand-dot">.</span></span>
          </a>
          <nav className="home-desktop-nav" aria-label="Main navigation">
            {navigation.map(item => <a key={item.href} href={item.href}>{item.label}</a>)}
          </nav>
          <div className={`home-header-actions${onLogout ? ' home-header-authenticated' : ''}`}>
            {onLogout && <button type="button" className="access-signout" aria-label="Sign out" title="Sign out" onClick={onLogout}><LogOut size={18} aria-hidden="true" /><span>Sign out</span></button>}
            <button type="button" className="home-button home-header-cta" onClick={startChat}>Get Started <ArrowUpRight size={16} aria-hidden="true" /></button>
            <button type="button" className="home-menu-toggle" ref={menuButtonRef} aria-label={menuOpen ? 'Close menu' : 'Open menu'} aria-expanded={menuOpen} aria-controls="home-mobile-nav" onClick={() => setMenuOpen(open => !open)}>
              {menuOpen ? <X size={22} aria-hidden="true" /> : <Menu size={22} aria-hidden="true" />}
            </button>
          </div>
        </div>
        {menuOpen && (
          <nav id="home-mobile-nav" className="home-mobile-nav" aria-label="Mobile navigation">
            {navigation.map(item => <a key={item.href} href={item.href} onClick={() => setMenuOpen(false)}>{item.label}<ArrowUpRight size={17} aria-hidden="true" /></a>)}
          </nav>
        )}
      </header>

      <main id="home-main" tabIndex={-1}>
        <section className="home-hero home-container" aria-labelledby="home-heading">
          <div className="home-hero-copy">
            <p className="home-eyebrow"><span /> Everyday nourishment, thoughtfully made</p>
            <h1 id="home-heading">A little inspiration.<br />A little <em>nourishment.</em></h1>
            <p className="home-hero-description">Good food starts with what works for you. Find recipe ideas for your preferences, your pantry, and your everyday life.</p>
            <div className="home-hero-actions">
              <button type="button" className="home-button" onClick={startChat}>Find your next meal <ArrowUpRight size={19} aria-hidden="true" /></button>
              <a className="home-text-link" href="#how-it-works">See how it works <ArrowRight size={17} aria-hidden="true" /></a>
            </div>
            <div className="home-hero-notes"><span><MessageCircle size={15} aria-hidden="true" /> Ask naturally</span><span><SlidersHorizontal size={15} aria-hidden="true" /> Make it your own</span></div>
            <p className="home-audience">Thoughtful recipe support for people navigating cancer care, and those cooking for them.</p>
          </div>
          <figure className="home-hero-art">
            <div className="home-meal-frame"><img src={homeMeal} alt="A bowl of quinoa, chickpeas, vegetables, and lemon on a linen-covered table" width="1254" height="1254" decoding="async" /></div>
            <div className="home-meal-note"><span><Leaf size={21} aria-hidden="true" /></span><div>Everyday ingredients.<br /><strong>A world of possibilities.</strong></div></div>
            <figcaption>Meal inspiration · AI-created image</figcaption>
          </figure>
        </section>

        <section className="home-sources home-container" aria-label="Recipe database sources">
          <div className="home-sources-bar">
            <div className="home-sources-lead">
              <p className="home-eyebrow"><span /> Evidence-informed nutrition</p>
              <p className="home-sources-heading">Familiar sources.<br /><strong>A thoughtful starting point.</strong></p>
            </div>
            <div className="home-source-org">
              <div className="home-org-crest home-org-crest-sage" aria-hidden="true">
                <svg viewBox="0 0 32 32" width="22" height="22" fill="none">
                  <path d="M16 5C11.5 9.5 9.5 14.2 11 19.5C12.2 23.6 15.8 26 16 26C16.2 26 19.8 23.6 21 19.5C22.5 14.2 20.5 9.5 16 5Z" stroke="currentColor" strokeWidth="1.6" strokeLinejoin="round" />
                  <path d="M16 11V25M16 17L19.5 14M16 20.5L12.5 17.5" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" />
                </svg>
              </div>
              <div className="home-org-text">
                <span>AICR</span>
                <small>World Cancer Research Fund /<br />American Institute for Cancer Research</small>
              </div>
            </div>
            <div className="home-source-org">
              <div className="home-org-crest home-org-crest-wheat" aria-hidden="true">
                <svg viewBox="0 0 32 32" width="22" height="22" fill="none">
                  <circle cx="16" cy="16" r="10.5" stroke="currentColor" strokeWidth="1.6" />
                  <path d="M16 10.5V21.5M10.5 16H21.5" stroke="currentColor" strokeWidth="1.6" strokeLinecap="round" />
                  <circle cx="16" cy="16" r="3" fill="currentColor" fillOpacity="0.18" />
                </svg>
              </div>
              <div className="home-org-text">
                <span>ACS</span>
                <small>American<br />Cancer Society</small>
              </div>
            </div>
            <div className="home-source-org">
              <div className="home-org-crest home-org-crest-terra" aria-hidden="true">
                <svg viewBox="0 0 32 32" width="22" height="22" fill="none">
                  <path d="M16 25.5C16 25.5 7 19.8 7 13.2C7 9.9 9.5 7.5 12.4 7.5C14.2 7.5 15.5 8.5 16 9.8C16.5 8.5 17.8 7.5 19.6 7.5C22.5 7.5 25 9.9 25 13.2C25 19.8 16 25.5 16 25.5Z" stroke="currentColor" strokeWidth="1.6" strokeLinejoin="round" />
                  <path d="M11.5 15.5H13.8L15.2 12.8L16.9 18L18.3 15.5H20.5" stroke="currentColor" strokeWidth="1.4" strokeLinecap="round" strokeLinejoin="round" />
                </svg>
              </div>
              <div className="home-org-text">
                <span>AHA</span>
                <small>American<br />Heart Association</small>
              </div>
            </div>
          </div>

          <div className="home-sources-story">
            <div className="home-sources-narrative">
              <p>
                ThriveWell recipes are based on nutrition recommendations from trusted cancer health organizations, including the World Cancer Research Fund / American Institute for Cancer Research and the American Cancer Society. These organizations study how food, exercise, and other healthy habits can help people stay well and lower their risk of cancer.
              </p>
              <p>
                Simple habits like eating more fruits and vegetables, whole grains, and fiber, and limiting processed sugar and meat can help lower cancer risk, improve heart health, and support general well-being.
              </p>
            </div>

            <div className="home-sources-graphics" aria-hidden="true">
              <div className="home-pillar-card home-pillar-sage">
                <span className="home-pillar-icon">
                  <svg viewBox="0 0 36 36" width="26" height="26" fill="none">
                    <circle cx="15.5" cy="20.5" r="7.5" fill="currentColor" fillOpacity="0.14" stroke="currentColor" strokeWidth="1.6" />
                    <path d="M15.5 13C15.5 9.5 18 7.5 21.5 7.5C21.5 10.8 19.2 13 15.5 13Z" fill="currentColor" fillOpacity="0.22" stroke="currentColor" strokeWidth="1.5" strokeLinejoin="round" />
                    <path d="M23 15.5C25.8 15.5 28 17.7 28 20.5C28 23.8 25.3 26.5 22 26.5" stroke="currentColor" strokeWidth="1.6" strokeLinecap="round" />
                    <circle cx="13" cy="18.5" r="1.2" fill="currentColor" />
                  </svg>
                </span>
                <div>
                  <strong>Fruits &amp; Vegetables</strong>
                  <small>Colorful plants &amp; phytonutrients</small>
                </div>
              </div>

              <div className="home-pillar-card home-pillar-wheat">
                <span className="home-pillar-icon">
                  <svg viewBox="0 0 36 36" width="26" height="26" fill="none">
                    <path d="M18 28V10" stroke="currentColor" strokeWidth="1.6" strokeLinecap="round" />
                    <path d="M18 15C14.2 14.8 12 12.5 12.2 9.2C15.5 9.4 17.8 11.7 18 15Z" fill="currentColor" fillOpacity="0.18" stroke="currentColor" strokeWidth="1.5" strokeLinejoin="round" />
                    <path d="M18 15C21.8 14.8 24 12.5 23.8 9.2C20.5 9.4 18.2 11.7 18 15Z" fill="currentColor" fillOpacity="0.18" stroke="currentColor" strokeWidth="1.5" strokeLinejoin="round" />
                    <path d="M18 21.5C14.2 21.3 12 19 12.2 15.7C15.5 15.9 17.8 18.2 18 21.5Z" fill="currentColor" fillOpacity="0.14" stroke="currentColor" strokeWidth="1.5" strokeLinejoin="round" />
                    <path d="M18 21.5C21.8 21.3 24 19 23.8 15.7C20.5 15.9 18.2 18.2 18 21.5Z" fill="currentColor" fillOpacity="0.14" stroke="currentColor" strokeWidth="1.5" strokeLinejoin="round" />
                  </svg>
                </span>
                <div>
                  <strong>Whole Grains &amp; Fiber</strong>
                  <small>Nourishing grains, beans &amp; legumes</small>
                </div>
              </div>

              <div className="home-pillar-card home-pillar-terra">
                <span className="home-pillar-icon">
                  <svg viewBox="0 0 36 36" width="26" height="26" fill="none">
                    <circle cx="18" cy="18" r="9.5" fill="currentColor" fillOpacity="0.12" stroke="currentColor" strokeWidth="1.6" />
                    <path d="M13 18H23" stroke="currentColor" strokeWidth="1.7" strokeLinecap="round" />
                    <path d="M15.2 13.8H20.8M15.2 22.2H20.8" stroke="currentColor" strokeWidth="1.3" strokeLinecap="round" strokeOpacity="0.55" />
                  </svg>
                </span>
                <div>
                  <strong>Mindful Limits</strong>
                  <small>Less processed sugar &amp; meat</small>
                </div>
              </div>

              <div className="home-pillar-card home-pillar-sky">
                <span className="home-pillar-icon">
                  <svg viewBox="0 0 36 36" width="26" height="26" fill="none">
                    <path d="M18 27.5C18 27.5 9.5 22 9.5 15.5C9.5 12.3 12 10 14.8 10C16.5 10 17.6 11 18 12.2C18.4 11 19.5 10 21.2 10C24 10 26.5 12.3 26.5 15.5C26.5 22 18 27.5 18 27.5Z" fill="currentColor" fillOpacity="0.16" stroke="currentColor" strokeWidth="1.6" strokeLinejoin="round" />
                    <path d="M13.5 17.5H15.8L17.1 14.8L18.8 20L20.1 17.5H22.5" stroke="currentColor" strokeWidth="1.4" strokeLinecap="round" strokeLinejoin="round" />
                  </svg>
                </span>
                <div>
                  <strong>Whole-Body Well-Being</strong>
                  <small>Lower cancer risk &amp; heart health</small>
                </div>
              </div>
            </div>
          </div>
        </section>

        <section id="how-it-works" className="home-section home-container" aria-labelledby="home-how-heading">
          <div className="home-section-heading"><p className="home-eyebrow">Simple by design</p><h2 id="home-how-heading">Less searching.<br /><em>More possibilities.</em></h2><p>You don’t need the perfect prompt. Just a place to start.</p></div>
          <div className="home-steps">
            {steps.map((step, index) => <article key={step.title} className="home-step"><div className="home-step-top"><step.icon size={26} strokeWidth={1.4} aria-hidden="true" /><span>0{index + 1}</span></div><h3>{step.title}</h3><p>{step.description}</p></article>)}
          </div>
        </section>

        <section id="recipes" className="home-inspiration home-container" aria-labelledby="home-inspiration-heading">
          <div className="home-inspiration-heading"><div><p className="home-eyebrow">There’s more than one way to begin</p><h2 id="home-inspiration-heading">What sounds good <em>today?</em></h2></div><p>Different days call for different meals. Start with the things that matter to you.</p></div>
          <div className="home-inspiration-grid">
            {inspirations.map(item => <article className={`home-inspiration-card home-tone-${item.tone}`} key={item.title}><span className="home-inspiration-icon"><item.icon size={29} strokeWidth={1.35} aria-hidden="true" /></span><p className="home-eyebrow">{item.label}</p><h3>{item.title}</h3><p className="home-example-prompt">{item.prompt}</p></article>)}
          </div>
          <div className="home-inspiration-footer"><span>A few ideas to get the conversation going.</span><button type="button" className="home-text-link" onClick={startChat}>Explore recipes <ArrowUpRight size={18} aria-hidden="true" /></button></div>
        </section>

        <section id="approach" className="home-approach home-section home-container" aria-labelledby="home-approach-heading">
          <div className="home-source-preview" aria-label="How recipe source labels work">
            <p className="home-eyebrow">Know where your ideas come from</p>
            <div className="home-provenance-card"><span className="home-source-badge"><ExternalLink size={13} aria-hidden="true" /> Published source</span><h3>A recipe you can trace.</h3><p>Database recipes include the original source name and a link to the recipe.</p><div className="home-source-names">AICR <span>·</span> ACS <span>·</span> AHA</div></div>
            <div className="home-provenance-card home-ai-card"><span className="home-ai-badge"><Sparkles size={13} aria-hidden="true" /> AI Generated</span><h3>A new idea, clearly labeled.</h3><p>When a new recipe is created by AI, the label makes that distinction clear.</p></div>
            <p className="home-source-note">Source attribution does not imply endorsement of Thrivewell.</p>
          </div>
          <div className="home-approach-copy"><p className="home-eyebrow">A little more clarity</p><h2 id="home-approach-heading">Thoughtful by design.<br /><em>Transparent by default.</em></h2><p>Recipe inspiration should come with context. Thrivewell looks for suitable database recipes first, and can use AI when a new idea is needed.</p><ul className="home-principles"><li><Check size={17} aria-hidden="true" /><span><strong>Sources you can follow</strong>Open the original link for recipes from the database.</span></li><li><Check size={17} aria-hidden="true" /><span><strong>Your preferences stay part of the conversation</strong>Refine ideas with follow-ups in the same chat.</span></li><li><Check size={17} aria-hidden="true" /><span><strong>Recipe support, not medical advice</strong>Keep your care team’s guidance at the center of your choices.</span></li></ul><a className="home-text-link" href="https://chicago.medicine.uic.edu/family-community-medicine/fcm-research/labs/vitality-lab/" target="_blank" rel="noopener noreferrer">Visit the UIC Vitality Lab <ArrowUpRight size={17} aria-hidden="true" /></a></div>
        </section>

        <section id="questions" className="home-faq home-container" aria-labelledby="home-faq-heading">
          <div><p className="home-eyebrow">Good to know</p><h2 id="home-faq-heading">A few things<br /><em>you might be wondering.</em></h2></div>
          <div className="home-faq-list">{questions.map(item => <details key={item.question}><summary>{item.question}<ChevronDown size={18} aria-hidden="true" /></summary><p>{item.answer}</p></details>)}</div>
        </section>

        <section className="home-final-cta home-container" aria-labelledby="home-cta-heading"><div><p className="home-eyebrow">One small step, one meal at a time</p><h2 id="home-cta-heading">Your next meal starts<br />with a <em>conversation.</em></h2><button type="button" className="home-button home-button-light" onClick={startChat}>Let’s find something good <ArrowUpRight size={19} aria-hidden="true" /></button></div><Leaf className="home-cta-leaf" size={230} strokeWidth={.6} aria-hidden="true" /></section>
      </main>

      <footer className="home-footer home-container"><div className="home-footer-top"><a className="home-brand" href="#home-top" aria-label="Thrivewell home"><Leaf aria-hidden="true" /><span>Thrivewell<span className="home-brand-dot">.</span></span></a><nav aria-label="Footer navigation"><a href="#how-it-works">How it works</a><a href="#approach">Our approach</a><a href="#questions">Questions</a></nav></div><div className="home-footer-bottom"><p>Recipe ideas, not medical advice. Please avoid sharing identifying health information.</p><span>© {new Date().getFullYear()} Thrivewell</span></div></footer>
    </div>
  );
};

export default LandingPage;
