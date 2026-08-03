import React, { useMemo, useState } from 'react'
import { fmt } from './util.js'

const ICON = { audio: '♪', image: '▣', video: '▶' }

/**
 * Elenco dei media organizzato in cartelle.
 * Le cartelle non esistono su disco: sono un'etichetta sul media, quindi
 * spostare un file nel bin non tocca nulla sul filesystem.
 */
export default function MediaBin({ project, run, setError, onOpenSource, onImport, uploading }) {
  const [open, setOpen] = useState({})
  const [dragOver, setDragOver] = useState(null)
  const media = project?.media || []

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

  const newFolder = () => {
    const name = prompt('Nome della cartella')
    if (name) setOpen((o) => ({ ...o, [name.trim()]: true }))
  }

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

  const Item = ({ m }) => (
    <div
      className="media" draggable
      onDragStart={(e) => {
        e.dataTransfer.setData('text/media', m.id)
        e.dataTransfer.effectAllowed = 'copyMove'
      }}
      onClick={() => onOpenSource(m)}
      onDoubleClick={() => run('add_clip', { media_id: m.id }).catch((e) => setError(e.message))}
      title="clic: apri nel monitor · doppio clic: accoda · trascina: timeline o cartella"
    >
      <div className="kind">{ICON[m.kind] || '▶'}</div>
      <div className="meta">
        <div className="mname">{m.name}</div>
        <div className="msub">
          {m.duration ? `${fmt(m.duration)} ` : ''}{m.resolution || ''}{m.audio ? ' ·♪' : ''}
        </div>
      </div>
      <button className="kf-btn" title="rimuovi dal progetto"
        onClick={(e) => {
          e.stopPropagation()
          run('remove_media', { media_id: m.id }).catch((err) => {
            if (err.message.includes('force') &&
              confirm(`${err.message}\n\nEliminare anche le clip?`)) {
              run('remove_media', { media_id: m.id, force: true }).catch((e2) => setError(e2.message))
            } else setError(err.message)
          })
        }}>✕</button>
    </div>
  )

  return (
    <div className="side">
      <div className="section-title">
        media
        <span className="spacer" />
        <button disabled={!project} onClick={newFolder} title="nuova cartella">📁+</button>
        <button disabled={!project} onClick={() => onImport(null)} title="importa file">+</button>
      </div>

      <div className={`medialist ${dragOver === '' ? 'droptarget' : ''}`} {...dropTarget('')}>
        {tree.folders.map(([name, items]) => (
          <div key={name}>
            <div className={`folder ${dragOver === name ? 'droptarget' : ''}`}
              {...dropTarget(name)}
              onClick={() => setOpen((o) => ({ ...o, [name]: !o[name] }))}>
              <span>{open[name] === false ? '▸' : '▾'} 📁 {name}</span>
              <span className="spacer" />
              <span className="hint">{items.length}</span>
            </div>
            {open[name] !== false && items.map((m) => <Item key={m.id} m={m} />)}
          </div>
        ))}
        {Object.keys(open).filter((f) => !tree.folders.some(([n]) => n === f)).map((f) => (
          <div key={f} className={`folder vuota ${dragOver === f ? 'droptarget' : ''}`} {...dropTarget(f)}>
            <span>📁 {f}</span><span className="spacer" /><span className="hint">trascina qui</span>
          </div>
        ))}

        {tree.root.map((m) => <Item key={m.id} m={m} />)}

        {project && !media.length && (
          <div className="hint" style={{ padding: 12, textAlign: 'center' }}>
            Nessun file.<br />Premi <b>+</b> oppure trascina qui i video dal desktop.
          </div>
        )}
        {uploading && <div className="hint" style={{ padding: 8 }}>copio i file… {uploading}</div>}
      </div>
    </div>
  )
}
