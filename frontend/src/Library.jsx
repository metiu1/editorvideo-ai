import React, { useMemo, useState } from 'react'

/**
 * Libreria di look, catene audio e transizioni gia' pronte.
 *
 * Il pannello proprieta' espone i mattoni con tutti i parametri; qui si sceglie
 * per nome. Clic = applica alla clip selezionata, trascina = applica alla clip
 * su cui lasci il mouse.
 */
export default function Library({ library, clip, onPreset, onTransition, setError }) {
  const [q, setQ] = useState('')
  const [tab, setTab] = useState('video')   // video | audio | transitions

  const items = useMemo(() => {
    const list = library?.[tab] || []
    const needle = q.trim().toLowerCase()
    const hit = needle
      ? list.filter((p) => `${p.name} ${p.desc || ''} ${p.group}`.toLowerCase().includes(needle))
      : list
    const groups = new Map()
    for (const p of hit) {
      if (!groups.has(p.group)) groups.set(p.group, [])
      groups.get(p.group).push(p)
    }
    return [...groups.entries()]
  }, [library, tab, q])

  const isTransition = tab === 'transitions'

  const apply = (item) => {
    if (isTransition) {
      if (!clip) { setError('seleziona prima una clip: la transizione va in coda a quella'); return }
      onTransition(item.id, item.duration)
      return
    }
    // senza clip selezionata i look video vanno sul master, cioe' su tutto il video
    if (!clip && tab === 'audio') { setError('seleziona la clip audio a cui applicarlo'); return }
    onPreset(item.id, clip?.id ?? null)
  }

  const target = isTransition
    ? (clip ? `in coda a ${clip.name || clip.id}` : 'nessuna clip selezionata')
    : (clip ? `su ${clip.name || clip.id}` : tab === 'audio' ? 'nessuna clip selezionata' : 'su tutto il video')

  return (
    <div className="side">
      <div className="section-title">libreria</div>

      <div className="tabs libtabs">
        <button className={tab === 'video' ? 'on' : ''} onClick={() => setTab('video')}>look</button>
        <button className={tab === 'audio' ? 'on' : ''} onClick={() => setTab('audio')}>audio</button>
        <button className={tab === 'transitions' ? 'on' : ''}
          onClick={() => setTab('transitions')}>transizioni</button>
      </div>

      <div style={{ padding: '6px 8px' }}>
        <input value={q} onChange={(e) => setQ(e.target.value)} placeholder="cerca…" />
      </div>

      <div className="medialist">
        {items.map(([group, list]) => (
          <div key={group}>
            <div className="libgroup">{group}</div>
            {list.map((p) => (
              <div
                key={p.id}
                className="preset"
                draggable
                onDragStart={(e) => {
                  e.dataTransfer.setData(isTransition ? 'text/transition' : 'text/preset', p.id)
                  if (isTransition) e.dataTransfer.setData('text/duration', String(p.duration))
                  e.dataTransfer.effectAllowed = 'copy'
                }}
                onClick={() => apply(p)}
                title={`${p.desc || ''}\nclic: applica · trascina: lascia sulla clip`}
              >
                <div className="pname">{p.name}</div>
                {p.desc && <div className="pdesc">{p.desc}</div>}
              </div>
            ))}
          </div>
        ))}
        {!items.length && <div className="hint" style={{ padding: 12 }}>Nessun risultato.</div>}
      </div>

      <div className="libfoot hint">{target}</div>
    </div>
  )
}
