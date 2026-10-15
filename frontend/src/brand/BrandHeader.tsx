import { ArrowLeft, ArrowUpRight } from 'lucide-react';
import './brand.css';

/** Share the restrained Eraneos frame across the demo hub and visual game. */
export default function BrandHeader({ game = false }: { game?: boolean }) {
  return <header className="er-header">
    <a href="/" aria-label="Eraneos demo home" className="er-logo"><img src="/brand/eraneos.svg" alt="eraneos" /></a>
    <span className="er-header-divider" /><span className="er-lab-label">AI playground</span>
    {game ? <a href="/" className="er-header-link"><ArrowLeft size={15} />All demos</a>
      : <a href="https://typesafe.ai/" target="_blank" rel="noreferrer" className="er-header-link">Powered by Jev<ArrowUpRight size={15} /></a>}
  </header>;
}
