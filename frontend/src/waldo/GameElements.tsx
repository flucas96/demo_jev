import { Alert, NumberInput, Select, Tooltip } from '@mantine/core';
import { Activity, Clock3, Coins, Hash } from 'lucide-react';
import { dollars } from '../api';
import Board from './Board';
import ModelIdentity, { ModelIcon } from './ModelIdentity';
import type { WaldoGameState } from './useWaldoGame';
import type { Metrics } from './types';

/** Shared model selector with recognizable provider logos. */
export function ModelPicker({ game }: { game: WaldoGameState }) {
  return <Select aria-label="Opponent model" label={game.pairedMode ? "Your first opponent" : "Opponent model"} value={game.model} onChange={value => { if (value) game.selectModel(value); }}
    data={game.models?.models.filter(option => !game.pairedMode || !option.id.startsWith('jev')).map(option => ({ value: option.id, label: option.label })) ?? []}
    comboboxProps={{ withinPortal: false }} leftSection={<ModelIcon model={game.model} size={21} />} renderOption={({ option }) => <ModelIdentity model={option.value} label={option.label} />}
    disabled={game.pairedMode && (game.locked || game.pendingPair)} searchable allowDeselect={false} className="benchmark-model" />;
}

export function DurationPicker({ game }: { game: WaldoGameState }) {
  return <div className="duration-field"><Clock3 size={16} /><NumberInput aria-label="Seconds per round" value={game.duration} onChange={game.setDuration} min={15} max={180} step={15} allowDecimal={false} allowNegative={false} disabled={game.locked || game.pendingPair} suffix=" s" size="sm" /></div>;
}

export function GameNotice({ game }: { game: WaldoGameState }) {
  return <>{(game.error || game.models?.error) && <Alert color="red" title="Unable to continue" className="waldo-alert">{game.error || game.models?.error}</Alert>}
    {game.models && (((game.pairedMode || game.model.startsWith('jev')) && !game.models.jev_configured) || (!game.model.startsWith('jev') && !game.models.gateway_configured)) && <Alert color="orange" className="waldo-alert">Configure the required API keys on the server.</Alert>}
    {game.match?.model_error && <Alert color="orange" className="waldo-alert" title="Model paused">{game.match.model_error}<button type="button" className="inline-retry" onClick={game.retry}>Try again</button></Alert>}</>;
}

export function Arena({ game }: { game: WaldoGameState }) {
  return <div className="waldo-arena">
    <Board who="human" player={game.match?.players.human} preview={game.catalog?.images[0]} active={game.active} started={!!game.match} modelError={false} onPick={game.submit} onSkip={game.skip} />
    <span className="arena-vs" aria-hidden="true">vs.</span>
    <Board who="jev" modelLabel={game.currentLabel} modelId={game.currentModel} player={game.match?.players.jev} preview={game.catalog?.images[0]} active={game.active} started={!!game.match} modelError={!!game.match?.model_error} onPick={game.submit} onSkip={game.skip} />
    {(game.phase === 'countdown' || game.phase === 'loading') && <div className="waldo-countdown" role="status"><span key={game.countdown}>{game.phase === 'loading' ? '…' : game.countdown}</span><p>{game.phase === 'loading' ? 'Preparing the arena' : <ModelIdentity model={game.currentModel} label={`You vs. ${game.upcomingLabel}`} size={26} />}</p></div>}
  </div>;
}

export function GameClock({ game }: { game: WaldoGameState }) {
  const seconds = Math.ceil((game.match?.remaining_ms ?? Number(game.duration) * 1000) / 1000);
  return <div className={`waldo-clock ${game.active && seconds <= 10 ? 'urgent' : ''}`} role="timer" aria-label={`${seconds} seconds left`}><span>{String(Math.floor(seconds / 60)).padStart(2, '0')}<b>:</b>{String(seconds % 60).padStart(2, '0')}</span></div>;
}

export function GameMetrics({ metrics }: { metrics?: Metrics }) {
  return <section className="waldo-telemetry" aria-label="Live model metrics">
    <div><Activity size={18} /><div><span className="telemetry-label">Last response</span><strong>{metrics?.last_ms != null ? Math.round(metrics.last_ms) : '—'}<small>ms</small></strong></div></div>
    <div><Clock3 size={17} /><div><span className="telemetry-label">Avg. response</span><strong>{metrics?.average_ms != null ? Math.round(metrics.average_ms) : '—'}<small>ms</small></strong></div></div>
    <div><Hash size={17} /><div><span className="telemetry-label">Model calls</span><strong>{metrics?.calls ?? 0}</strong></div></div>
    <Tooltip label="Gateway-reported cost includes caching. Otherwise calculated from reported tokens and list prices. Pending or failed calls can add charges." multiline w={300}><div><Coins size={17} /><div><span className="telemetry-label">Cost{metrics?.cost_partial ? '*' : ''}</span><strong>{dollars(metrics ? metrics.cost_usd : 0)}</strong></div></div></Tooltip>
  </section>;
}
