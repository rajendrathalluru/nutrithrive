import React, { useEffect, useRef, useState } from 'react';
import { ArrowRight, ArrowUpRight, Check, ChevronDown, Clock3, CookingPot, ExternalLink, Leaf, Menu, MessageCircle, Package, SlidersHorizontal, Sparkles, Sprout, X } from 'lucide-react';
import homeMeal from '../assets/images/home-meal.jpg';
import './LandingPage.css';

interface LandingPageProps {
  onGetStarted?: () => void;
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

const LandingPage: React.FC<LandingPageProps> = ({ onGetStarted }) => {
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
          <div className="home-header-actions">
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
          <p>Familiar sources.<br /><strong>A thoughtful starting point.</strong></p>
          <div><span>AICR</span><small>American Institute for<br />Cancer Research</small></div>
          <div><span>ACS</span><small>American<br />Cancer Society</small></div>
          <div><span>AHA</span><small>American<br />Heart Association</small></div>
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
