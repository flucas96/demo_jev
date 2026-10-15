import { useEffect, useRef, useState } from 'react';
import type { PointerEvent } from 'react';
import { Alert, Checkbox, Modal, SegmentedControl } from '@mantine/core';
import { ArrowLeft, Check, Expand, Pencil, RotateCcw, Save } from 'lucide-react';
import { api } from '../api';
import BrandHeader from '../brand/BrandHeader';
import { boxStyle, paddedBox } from './geometry';
import type { Box, ReferenceCatalog, ReferencePuzzle } from './types';
import './references.css';

/** Render the exact saved scoring regions, with an optional tolerance boundary. */
function Outlines({ puzzle, tolerance }: { puzzle: ReferencePuzzle; tolerance: boolean }) {
  return <>
    {tolerance && <span className="reference-outline tolerance" style={boxStyle(puzzle.tolerance)} />}
    <span className="reference-outline body" style={boxStyle(puzzle.reference)} />
    <span className="reference-outline head" style={boxStyle(puzzle.head)} />
  </>;
}

/** Let the reviewer redraw either rectangle and persist one shared source annotation. */
function Editor({ original, padding, onSaved }: { original: ReferencePuzzle; padding: number; onSaved: (puzzle: ReferencePuzzle) => void }) {
  const [draft, setDraft] = useState(original);
  const [part, setPart] = useState<'head' | 'reference'>('head');
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [saved, setSaved] = useState(false);
  const [tolerance, setTolerance] = useState(true);
  const start = useRef<{ x: number; y: number } | null>(null);
  const beforeDrag = useRef(original);
  const dirty = JSON.stringify(draft.head) !== JSON.stringify(original.head) || JSON.stringify(draft.reference) !== JSON.stringify(original.reference);

  function point(event: PointerEvent<HTMLDivElement>) {
    const rect = event.currentTarget.getBoundingClientRect();
    return { x: Math.max(0, Math.min(1, (event.clientX - rect.left) / rect.width)), y: Math.max(0, Math.min(1, (event.clientY - rect.top) / rect.height)) };
  }
  function down(event: PointerEvent<HTMLDivElement>) {
    if (saving || event.button !== 0) return;
    event.preventDefault(); event.currentTarget.setPointerCapture(event.pointerId);
    start.current = point(event); beforeDrag.current = draft; setSaved(false); setError(null);
  }
  function draw(event: PointerEvent<HTMLDivElement>): Box | null {
    if (!start.current) return null;
    const end = point(event);
    return { left: Math.min(start.current.x, end.x), right: Math.max(start.current.x, end.x), top: Math.min(start.current.y, end.y), bottom: Math.max(start.current.y, end.y) };
  }
  function update(box: Box) {
    setDraft(previous => ({ ...previous, [part]: box, tolerance: paddedBox(part === 'reference' ? box : previous.reference, padding) }));
  }
  function up(event: PointerEvent<HTMLDivElement>) {
    const box = draw(event); start.current = null;
    if (event.currentTarget.hasPointerCapture(event.pointerId)) event.currentTarget.releasePointerCapture(event.pointerId);
    if (box && box.right - box.left > .002 && box.bottom - box.top > .002) update(box);
    else setDraft(beforeDrag.current);
  }
  async function save() {
    const b = draft.reference, h = draft.head;
    if (h.left < b.left || h.right > b.right || h.top < b.top || h.bottom > b.bottom) {
      setError('Die grüne Kopfbox muss innerhalb der blauen Körperbox liegen. Wenn nur der Kopf sichtbar ist, können beide gleich groß sein.'); return;
    }
    setSaving(true); setError(null);
    try {
      const result = await api<ReferencePuzzle>(`/api/waldo/references/${original.id}`, { method: 'PUT', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ reference: b, head: h }) });
      setDraft(result); onSaved(result); setSaved(true);
    } catch (failure) { setError(failure instanceof Error ? failure.message : 'Speichern fehlgeschlagen.'); }
    finally { setSaving(false); }
  }
  return <div className="reference-editor">
    <div className="reference-tools"><SegmentedControl aria-label="Box bearbeiten" value={part} onChange={value => setPart(value as 'head' | 'reference')} disabled={saving} data={[{ value: 'head', label: 'Kopf' }, { value: 'reference', label: 'Sichtbarer Körper' }]} /><span><Pencil size={13} />Neue Box im Bild ziehen</span><Checkbox label="Toleranz zeigen" checked={tolerance} onChange={event => setTolerance(event.currentTarget.checked)} size="xs" /></div>
    <div className={`reference-picture editable editing-${part}`} style={{ aspectRatio: `${draft.width}/${draft.height}`, width: `min(100%, calc((100dvh - 285px) * ${draft.width / draft.height}))`, margin: '0 auto' }} onPointerDown={down} onPointerMove={event => { const box = draw(event); if (box) update(box); }} onPointerUp={up} onPointerCancel={() => { start.current = null; setDraft(beforeDrag.current); }} aria-label={`${part === 'head' ? 'Kopfbox' : 'Körperbox'} neu zeichnen`}>
      <img src={draft.url} alt="Waldo-Szene mit bearbeitbaren Referenzboxen" draggable={false} /><Outlines puzzle={draft} tolerance={tolerance} />
    </div>
    {error && <Alert color="red" role="alert">{error}</Alert>}
    <div className="reference-savebar"><span>{saved ? <><Check size={15} />Gespeichert · gilt ab dem nächsten Duell</> : dirty ? 'Ungespeicherte Änderungen' : 'Gespeicherte Referenz'}</span><button className="reference-reset" type="button" onClick={() => { setDraft(original); setError(null); setSaved(false); }} disabled={saving || !dirty}><RotateCcw size={14} />Zurücksetzen</button><button type="button" className="er-button" onClick={() => void save()} disabled={saving || !dirty}><Save size={14} />{saving ? 'Speichert …' : 'Korrektur speichern'}</button></div>
    <p className="reference-editor-note">Korrekturen bleiben nach einem Neustart erhalten und gelten ab dem nächsten Duell. Bilder und Jev-Anfragen bleiben unverändert.</p>
  </div>;
}

/** Keep editable solutions separate from the uncluttered competitive game screen. */
export default function References() {
  const [catalog, setCatalog] = useState<ReferenceCatalog | null>(null);
  const [selected, setSelected] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [tolerance, setTolerance] = useState(true);
  useEffect(() => {
    const controller = new AbortController(); setError(null); setCatalog(null);
    void api<ReferenceCatalog>('/api/waldo/references', { signal: controller.signal }).then(setCatalog).catch((failure: unknown) => {
      if (!controller.signal.aborted) setError(failure instanceof Error ? failure.message : 'Referenzen konnten nicht geladen werden.');
    });
    return () => controller.abort();
  }, []);
  const picture = catalog?.images.find(item => item.id === selected);
  return <div className="er-page references-page"><BrandHeader game /><main className="reference-main">
    <div className="reference-intro"><div><a href="/waldo" className="reference-back"><ArrowLeft size={14} />Zum Duell</a><h1>Referenzboxen<span>.</span></h1><p>Prüfen. Korrigieren. Fair spielen.</p></div></div>
    <div className="reference-legend"><span><i className="head" />Kopf</span><span><i className="body" />Sichtbarer Körper</span><span><i className="tolerance" />Toleranz · 20 % Rand</span><Checkbox label="Toleranz zeigen" checked={tolerance} onChange={event => setTolerance(event.currentTarget.checked)} size="xs" /></div>
    <p className="reference-rule">Dein Klick zählt im orangefarbenen Bereich. Jevs Antwortbox erhält <b>{Math.round((catalog?.answer_padding ?? .30) * 100)} % Rand</b> zum Kopf-Abgleich und umfasst damit mindestens <b>{Math.round((catalog?.head_coverage ?? .5) * 100)} % des Kopfes</b>. Mindestens <b>{Math.round((catalog?.box_precision ?? .55) * 100)} % seiner ursprünglichen Box</b> liegen im orangefarbenen Bereich.</p>
    {error && <Alert color="red">{error}</Alert>}
    {!catalog && !error && <p role="status">Referenzen werden geladen …</p>}
    <div className="reference-grid">{catalog?.images.map(item => <button type="button" className="reference-card" key={item.id} onClick={() => setSelected(item.id)} aria-label={`${item.title} prüfen und korrigieren`}><div className="reference-thumbnail"><div className="reference-picture" style={{ aspectRatio: `${item.width}/${item.height}` }}><img src={item.url} alt={item.title} loading="lazy" /><Outlines puzzle={item} tolerance={tolerance} /></div></div><div className="reference-card-footer"><strong>{item.title}</strong><span>Prüfen & korrigieren<Expand size={14} /></span></div></button>)}</div>
  </main><footer className="er-footer"><span>Eraneos AI playground</span><a href="/waldo">Zurück zum Spiel ↗</a></footer>
    <Modal opened={!!picture} onClose={() => setSelected(null)} title={picture ? `${picture.title} · Referenz bearbeiten` : 'Referenz bearbeiten'} size="min(1100px, 96vw)" centered className="reference-modal" closeOnClickOutside={false}>
      {picture && catalog && <Editor key={picture.id} original={picture} padding={catalog.padding} onSaved={updated => setCatalog(previous => previous ? { ...previous, images: previous.images.map(item => item.id === updated.id ? updated : item) } : previous)} />}
    </Modal>
  </div>;
}
