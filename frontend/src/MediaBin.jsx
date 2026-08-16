import React, { useMemo, useState } from 'react'
import Icon from './Icons.jsx'
import useMediaAssets from './mediaAssets.js'
import { fmt } from './util.js'

const ICON = { audio: 'audio', image: 'immagine', video: 'video' }

// Misure del riquadro di anteprima, in pixel. Servono qui e non solo nel CSS
// perche' la striscia di fotogrammi si posiziona calcolando quale riquadro
// mostrare, e il conto vuole numeri.
const TH_W = 52
const TH_H = 30

/**
 * Un fotogramma preso dal mezzo del filmato.
 *
 * La striscia e' un'unica immagine con un fotogramma per secondo: se ne mostra
 * uno spostando lo sfondo, senza chiedere niente in piu' al server. Si prende
 * quello centrale perche' i primi secondi sono spesso neri o una sigla.
 */
function Miniatura({ strip }) {
  const w = Math.max(2, Math.round(TH_H * (strip.tile_width / strip.tile_height)))
  const scelto = Math.floor(strip.tiles / 2)
  return (
    <div className="thumb" style={{
      backgroundImage: `url(${strip.url})`,
      backgroundSize: `${strip.tiles * w}px ${TH_H}px`,
      backgroundPosition: `${-scelto * w + (TH_W - w) / 2}px center`,
    }} />
  )
}

/** Forma d'onda in miniatura: dice a colpo d'occhio dove c'e' segnale. */
function Onda({ peaks }) {
  const punti = 26
  const passo = Math.max(1, Math.floor(peaks.length / punti))
  const barre = []
  for (let i = 0; i < peaks.length && barre.length < punti; i += passo) {
    barre.push(Math.max(...peaks.slice(i, i + passo)))
  }
  return (
    <div className="thumb onda">
      {barre.map((v, i) => (
        // eslint-disable-next-line react/no-array-index-key
        <i key={i} style={{ height: `${Math.max(8, v * 100)}%` }} />
      ))}
    </div>
  )
}

/**
 * Elenco dei media organizzato in cartelle.
 * Le cartelle non esistono su disco: sono un'etichetta sul media, quindi
 * spostare un file nel bin non tocca nulla sul filesystem.
 */
export default function MediaBin({ project, run, setError, onOpenSource, onImport, uploading, ask }) {
  const [open, setOpen] = useState({})
  const [dragOver, setDragOver] = useState(null)
  const [newFolder, setNewFolder] = useState(null)   // nome in scrittura, null = nessuno
  const media = project?.media || []
  const assets = useMediaAssets(media)

  const tree = useMemo(() => {
    const folders = new Map()
    const root = []
    for (const m of media) {
      const key = (m.folder || '').trim()
      if (!key) { root.push(m); continue }
      if (!folders.has(key)) folders.set(key, [])
      folders.get(key).push(m)
    }
    return { root, folders: [...folders.entries()].sort((a, b) => a[0].localeCompare(b[0])) }
  }, [media])

  const move = (mediaId, folder) =>
    run('set_media', { media_id: mediaId, folder }).catch((e) => setError(e.message))

  const dropTarget = (folder) => ({
    onDragOver: (e) => { e.preventDefault(); setDragOver(folder) },
    onDragLeave: () => setDragOver((f) => (f === folder ? null : f)),
    onDrop: (e) => {
      e.preventDefault()
      e.stopPropagation()
      setDragOver(null)
      const id = e.dataTransfer.getData('text/media')
      if (id) { move(id, folder); return }
      if (e.dataTransfer.files?.length) onImport(e.dataTransfer.files, folder)
    },
  })

  const removeMedia = (m) => run('remove_media', { media_id: m.id }).catch((err) => {
    if (!err.message.includes('force')) { setError(err.message); return }
    ask({
      title: 'Il media è in uso',
      message: `${err.message}\n\nEliminando ${m.name} spariranno anche quelle clip dalla timeline.`,
      ok: 'elimina comunque', danger: true,
      onOk: () => run('remove_media', { media_id: m.id, force: true })
        .catch((e2) => setError(e2.message)),
    })
  })

  const Item = ({ m }) => {
    const strip = assets.strip(m)
    const peaks = m.kind === 'audio' ? assets.peaks(m) : null
    return (
    <div
      className="media" draggable
      onDragStart={(e) => {
        e.dataTransfer.setData('text/media', m.id)
        e.dataTransfer.effectAllowed = 'copyMove'
      }}
      onClick={() => onOpenSource(m)}
      onDoubleClick={() => run('add_clip', { media_id: m.id }).catch((e) => setError(e.message))}
      title="clic: apri nel monitor · doppio clic: accoda in timeline · trascina: timeline o cartella"
    >
      {/* finche' l'anteprima non e' arrivata resta l'icona: il riquadro ha
          comunque la sua misura, cosi' l'elenco non sobbalza quando arriva */}
      {strip?.url ? <Miniatura strip={strip} />
        : peaks?.length ? <Onda peaks={peaks} />
          : <div className="thumb vuoto"><Icon name={ICON[m.kind] || 'video'} /></div>}
      <div className="meta">
        <div className="mname">{m.name}</div>
        <div className="msub">
          {m.duration ? `${fmt(m.duration)} ` : ''}{m.resolution || ''}{m.audio ? ' · audio' : ''}
        </div>
      </div>
      <button className="icon sm danger" title="Togli dal progetto"
        onClick={(e) => { e.stopPropagation(); removeMedia(m) }}>
        <Icon name="chiudi" size={13} />
      </button>
    </div>
    )
  }

  return (
    <div className="side">
      <div className="section-title">
        media
        <span className="spacer" />
        <button className="icon sm" disabled={!project} title="Nuova cartella"
          onClick={() => setNewFolder('')}><Icon name="cartellaPiu" size={14} /></button>
        <button className="icon sm" disabled={!project} title="Importa file dal disco"
          onClick={() => onImport(null)}><Icon name="piu" size={14} /></button>
      </div>

      <div className={`medialist ${dragOver === '' ? 'droptarget' : ''}`} {...dropTarget('')}>
        {newFolder !== null && (
          <div className="folder">
            <Icon name="cartella" />
            <input autoFocus value={newFolder} placeholder="nome della cartella"
              style={{ height: 20 }}
              onChange={(e) => setNewFolder(e.target.value)}
              onBlur={() => setNewFolder(null)}
              onKeyDown={(e) => {
                if (e.key === 'Escape') setNewFolder(null)
                if (e.key === 'Enter' && newFolder.trim()) {
                  setOpen((o) => ({ ...o, [newFolder.trim()]: true }))
                  setNewFolder(null)
                }
              }} />
          </div>
        )}

        {tree.folders.map(([name, items]) => (
          <div key={name}>
            <div className={`folder ${dragOver === name ? 'droptarget' : ''}`}
              {...dropTarget(name)}
              onClick={() => setOpen((o) => ({ ...o, [name]: !o[name] }))}>
              <Icon name={open[name] === false ? 'giu' : 'su'} size={13} />
              <Icon name="cartella" />
              <span>{name}</span>
              <span className="spacer" />
              <span className="hint">{items.length}</span>
            </div>
            {open[name] !== false && items.map((m) => <Item key={m.id} m={m} />)}
          </div>
        ))}

        {Object.keys(open).filter((f) => !tree.folders.some(([n]) => n === f)).map((f) => (
          <div key={f} className={`folder vuota ${dragOver === f ? 'droptarget' : ''}`} {...dropTarget(f)}>
            <Icon name="cartella" /><span>{f}</span>
            <span className="spacer" /><span className="hint">trascina qui</span>
          </div>
        ))}

        {tree.root.map((m) => <Item key={m.id} m={m} />)}

        {project && !media.length && (
          <div className="hint" style={{ padding: 16, textAlign: 'center' }}>
            Nessun file.<br />Usa <b>+</b> oppure trascina qui i video dal desktop.
          </div>
        )}
        {!project && (
          <div className="hint" style={{ padding: 16, textAlign: 'center' }}>
            Nessun progetto aperto.
          </div>
        )}
        {uploading && (
          <div className="hint" style={{ padding: 10, display: 'flex', gap: 7, alignItems: 'center' }}>
            <Icon name="attesa" className="spin" />copio i file… {uploading}
          </div>
        )}
      </div>
    </div>
  )
}
