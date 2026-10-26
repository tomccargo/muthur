import { useEffect, useState } from 'react';
import { api, type SubResult } from '../api';
import { Dot, Loading } from '../components';
import { count, language } from '../labels';
import { Link } from '../nav';

// What a result has going for it, and against it: a subtitle made for this very file fits; one from the same
// release group, source and resolution usually does; translated or foreign-parts-only ones rarely are what you want.
function Facts({ s }: { s: SubResult }) {
  const facts = [
    s.hearingImpaired && 'for the hard of hearing',
    s.forced && 'foreign parts only',
    s.fps && `${s.fps} fps`,
    s.parts > 1 && `${s.parts} parts`,
    count(s.downloads, 'download'),
    s.votes > 0 && `rated ${s.rating.toFixed(1)} by ${s.votes}`,
    s.uploader && `by ${s.uploader}${s.rank ? ` (${s.rank})` : ''}`,
    s.trusted && 'trusted source',
    s.uploaded,
  ].filter(Boolean) as string[];
  return <span className="small muted">{facts.join(' · ')}</span>;
}

// "Find subtitles" for one video (an episode's menu, a film's page): OpenSubtitles.com searched by the video's IDs and
// its file's fingerprint, the results listed with what helps choose, and only the one picked is downloaded
// (DESIGN.md §1.9: the reader decides, muthur shows why).
export function SubtitleSearch({ path }: { path: string }) {
  const [data, setData] = useState<{ file: string; results: SubResult[]; count: number; allowed: number | null } | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState<number | null>(null);
  const [saved, setSaved] = useState<string | null>(null);
  const [all, setAll] = useState(false);

  useEffect(() => {
    setData(null);
    setError(null);
    api.subtitleSearch(path).then(setData).catch((e: Error) => setError(e.message));
  }, [path]);

  const use = (s: SubResult) => {
    setBusy(s.fileId);
    setError(null);
    api.subtitleSave(path, s.fileId, s.language)
      .then((r) => setSaved(`Saved as ${r.saved}${r.remaining != null ? ` · ${count(r.remaining, 'download')} left today` : ''}. Kodi finds it the next time the video plays.`))
      .catch((e: Error) => setError(e.message))
      .finally(() => setBusy(null));
  };

  if (error) {
    return (
      <div className="banner banner-error" role="alert" style={{ flexDirection: 'column', alignItems: 'flex-start' }}>
        <span>{error}</span>
        {/Settings/.test(error) && <Link to="/settings">Open Settings</Link>}
      </div>
    );
  }
  if (!data) return <Loading rows={3} label="Searching OpenSubtitles" />;
  const shown = all ? data.results : data.results.slice(0, 8);
  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: 8 }}>
      {saved && <div className="banner banner-note" role="status">{saved}</div>}
      <span className="small muted">
        {data.count ? `${count(data.count, 'subtitle')} on OpenSubtitles for ` : 'Nothing on OpenSubtitles for '}
        <span className="mono">{data.file}</span>
        {data.count ? ' · made for this file first, then the closest release' : ''}
      </span>
      {data.count > 0 && (
        <ul className="rows">
          {shown.map((s) => (
            <li key={s.fileId} style={{ flexDirection: 'column', alignItems: 'stretch', gap: 3 }}>
              <span className="actions" style={{ justifyContent: 'space-between', alignItems: 'baseline' }}>
                <span style={{ minWidth: 0 }}>
                  <strong>{language(s.language)}</strong>{' '}
                  <span className="mono small" style={{ wordBreak: 'break-all' }}>{s.release}</span>
                </span>
                <button className="btn btn-secondary btn-sm" type="button" aria-busy={busy === s.fileId} disabled={busy !== null}
                  onClick={() => use(s)}>Use this one</button>
              </span>
              <span className="actions" style={{ gap: '4px 12px' }}>
                {s.hashMatch && <span className="status small"><Dot kind="dot-success" />Made for this exact file</span>}
                {!s.hashMatch && s.same.length > 0 && <span className="status small"><Dot kind="dot-success" />Same {s.same.join(' · ')}</span>}
                {!s.hashMatch && !s.same.length && <span className="status small"><Dot />Another release: timing may be off</span>}
                {(s.aiTranslated || s.machineTranslated) && (
                  <span className="status small"><Dot kind="dot-warning" />{s.machineTranslated ? 'Machine translated' : 'AI translated'}</span>
                )}
              </span>
              <Facts s={s} />
              {s.comments && <span className="small muted" style={{ fontStyle: 'italic' }}>“{s.comments}”</span>}
            </li>
          ))}
        </ul>
      )}
      {data.results.length > shown.length && (
        <button type="button" className="btn-link small" style={{ alignSelf: 'flex-start' }} onClick={() => setAll(true)}>
          Show all {data.results.length}
        </button>
      )}
    </div>
  );
}
