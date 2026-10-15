import { ArrowUpRight, Gamepad2, Inbox, ScanSearch, Waypoints } from 'lucide-react';
import BrandHeader from './BrandHeader';
import './home.css';

const demos = [
  { title: 'Tickets verteilen.', label: 'Jira Triage', detail: '20 Anfragen. Parallel entschieden.', href: '/#queue', Icon: Inbox, number: '02' },
  { title: 'Im richtigen Moment.', label: 'Lantern Run', detail: 'Springen, ducken oder stehen. Jev entscheidet.', href: '/#runner', Icon: Gamepad2, number: '03' },
  { title: 'Zug um Zug.', label: 'Snake', detail: 'Ein Spielfeld aus Zeichen. Eine Entscheidung pro Zug.', href: '/#snake', Icon: Waypoints, number: '04' },
];

/** Provide one clear entry point to the existing demos and the new visual race. */
export default function DemoHome() {
  return <div className="er-page er-home"><BrandHeader />
    <main className="er-home-main">
      <div className="er-home-intro"><p className="er-kicker"><span />Intelligenz zum Ausprobieren</p><h1>Weniger erklären.<br />Mehr erleben.</h1><p>Sehen. Entscheiden. Handeln.<br />Entdecke, was spezialisierte KI heute kann.</p></div>
      <a className="er-feature" href="/waldo"><div className="er-feature-copy"><span className="er-feature-label"><ScanSearch size={15} />NEU · VISION + BOX</span><h2>Spot on.</h2><p>Dein Blick gegen Jev.<br />Wer findet Waldo in 60 Sekunden?</p><span className="er-feature-cta">Duell starten <ArrowUpRight size={18} /></span></div><div className="er-feature-art"><img src="/api/waldo/images/scene-16-sprint" alt="Bunter Ausschnitt eines Waldo-Suchbilds" /><div className="er-art-focus"><i /><i /><i /><i /></div><span className="er-feature-tag">Mensch <span>vs.</span> Jev</span></div></a>
      <div className="er-demo-grid">{demos.map(({title,label,detail,href,Icon,number})=><a href={href} className="er-demo-card" key={href}><div><Icon size={22} strokeWidth={1.3} /><span>{number}</span></div><span className="er-kicker">{label}</span><h2>{title}</h2><p>{detail}</p><ArrowUpRight size={20} className="er-demo-arrow" /></a>)}</div>
    </main><footer className="er-footer"><span>Eraneos AI playground</span><span>Live-Modelle. Echte Entscheidungen.</span></footer>
  </div>;
}
