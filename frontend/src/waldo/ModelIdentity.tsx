import { UserRound } from 'lucide-react';

/** Keep model identities recognizable across selection, gameplay, and results. */
export function ModelIcon({ model, size = 22 }: { model: string; size?: number }) {
  if (model === 'human') return <UserRound size={size} aria-hidden="true" className="human-icon" />;
  const provider = model.startsWith('jev') ? 'jev' : model.startsWith('claude') ? 'claude' : model.startsWith('gemini') ? 'gemini' : 'openai';
  return <img className={`model-icon model-icon-${provider}`} src={`/brand/models/${provider}.${provider === 'jev' ? 'png' : 'svg'}`} width={size} height={size} alt="" aria-hidden="true" />;
}

export default function ModelIdentity({ model, label, size = 20 }: { model: string; label: string; size?: number }) {
  return <span className="model-identity"><ModelIcon model={model} size={size} /><span>{label}</span></span>;
}
