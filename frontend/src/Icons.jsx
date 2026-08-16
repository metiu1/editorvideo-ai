import React from 'react'

/**
 * Icone dell'interfaccia.
 *
 * Disegnate a tratto, monocromatiche, che ereditano il colore del testo: le
 * emoji cambiano forma su ogni sistema, sono colorate e non si allineano con il
 * testo accanto. Un editor video passa ore sotto gli occhi: le icone devono
 * sparire finche' non servono, non attirare l'attenzione.
 */

const paths = {
  // --- file e progetto
  nuovo: <><path d="M13 3H6a1 1 0 0 0-1 1v16a1 1 0 0 0 1 1h12a1 1 0 0 0 1-1V9z" /><path d="M13 3v6h6" /></>,
  apri: <path d="M3 7a1 1 0 0 1 1-1h5l2 2h8a1 1 0 0 1 1 1v9a1 1 0 0 1-1 1H4a1 1 0 0 1-1-1z" />,
  salva: <><path d="M4 4h12l4 4v12H4z" /><path d="M8 4v6h8V4M8 20v-6h8v6" /></>,
  esporta: <><path d="M12 15V3" /><path d="m8 7 4-4 4 4" /><path d="M4 15v4a1 1 0 0 0 1 1h14a1 1 0 0 0 1-1v-4" /></>,

  // --- modifica
  annulla: <><path d="M3 8h11a5 5 0 0 1 0 10H8" /><path d="m7 4-4 4 4 4" /></>,
  ripeti: <><path d="M21 8H10a5 5 0 0 0 0 10h6" /><path d="m17 4 4 4-4 4" /></>,
  piu: <path d="M12 5v14M5 12h14" />,
  meno: <path d="M5 12h14" />,
  chiudi: <path d="M6 6l12 12M18 6L6 18" />,
  cestino: <><path d="M4 7h16" /><path d="M9 7V5a1 1 0 0 1 1-1h4a1 1 0 0 1 1 1v2" /><path d="M6 7v13a1 1 0 0 0 1 1h10a1 1 0 0 0 1-1V7" /><path d="M10 11v6M14 11v6" /></>,
  taglia: <><circle cx="6" cy="6" r="2.5" /><circle cx="6" cy="18" r="2.5" /><path d="M8.1 7.4 20 18M8.1 16.6 20 6" /></>,

  // --- riproduzione
  play: <path d="M7 4.5v15l13-7.5z" fill="currentColor" stroke="none" />,
  pausa: <><rect x="6.5" y="4.5" width="4" height="15" rx="1" fill="currentColor" stroke="none" /><rect x="13.5" y="4.5" width="4" height="15" rx="1" fill="currentColor" stroke="none" /></>,
  inizio: <><path d="M6 5v14" /><path d="M20 5 9 12l11 7z" fill="currentColor" stroke="none" /></>,

  // --- media
  video: <><rect x="2.5" y="6" width="14" height="12" rx="1.5" /><path d="m16.5 13 5 3V8l-5 3z" /></>,
  audio: <><path d="M9 18V5l11-2v13" /><circle cx="6" cy="18" r="3" /><circle cx="17" cy="16" r="3" /></>,
  immagine: <><rect x="3" y="4" width="18" height="16" rx="1.5" /><circle cx="8.5" cy="9.5" r="1.8" /><path d="m3 17 5-4 4 3 4-4 5 5" /></>,
  testo: <><path d="M5 6V4h14v2" /><path d="M12 4v16" /><path d="M9 20h6" /></>,
  cartella: <path d="M3 7a1 1 0 0 1 1-1h5l2 2h8a1 1 0 0 1 1 1v9a1 1 0 0 1-1 1H4a1 1 0 0 1-1-1z" />,
  cartellaPiu: <><path d="M3 7a1 1 0 0 1 1-1h5l2 2h8a1 1 0 0 1 1 1v9a1 1 0 0 1-1 1H4a1 1 0 0 1-1-1z" /><path d="M12 11v6M9 14h6" /></>,

  // --- tracce
  occhio: <><path d="M2.5 12S6 5.5 12 5.5 21.5 12 21.5 12 18 18.5 12 18.5 2.5 12 2.5 12" /><circle cx="12" cy="12" r="3" /></>,
  occhioNo: <><path d="M4 4.5 20 19.5" /><path d="M9.6 6C10.4 5.7 11.2 5.5 12 5.5c6 0 9.5 6.5 9.5 6.5a18 18 0 0 1-3.2 3.9" /><path d="M6.5 8.2A18 18 0 0 0 2.5 12S6 18.5 12 18.5c1.3 0 2.4-.3 3.4-.7" /><path d="M10 10a3 3 0 0 0 4 4" /></>,
  altoparlante: <><path d="M4 9.5h3.5L12 5.5v13L7.5 14.5H4z" /><path d="M16 9.2a4 4 0 0 1 0 5.6" /><path d="M18.6 6.6a7.5 7.5 0 0 1 0 10.8" /></>,
  altoparlanteNo: <><path d="M4 9.5h3.5L12 5.5v13L7.5 14.5H4z" /><path d="m16.5 9.5 5 5M21.5 9.5l-5 5" /></>,
  lucchetto: <><rect x="4.5" y="10.5" width="15" height="10" rx="1.5" /><path d="M8 10.5V7a4 4 0 0 1 8 0v3.5" /></>,
  lucchettoAperto: <><rect x="4.5" y="10.5" width="15" height="10" rx="1.5" /><path d="M8 10.5V7a4 4 0 0 1 7.5-2" /></>,
  su: <path d="m6 14 6-6 6 6" />,
  giu: <path d="m6 10 6 6 6-6" />,

  // --- pannelli
  cerca: <><circle cx="10.5" cy="10.5" r="6.5" /><path d="m15.5 15.5 4.5 4.5" /></>,
  keyframe: <path d="M12 4.5 19.5 12 12 19.5 4.5 12z" />,
  invia: <path d="M4 12 20.5 4.5 16 20.5l-4-6.5z" />,
  assistente: <><path d="M12 3.5 13.9 9l5.6 1.9-5.6 1.9L12 18.5 10.1 12.8 4.5 10.9 10.1 9z" /><path d="M18.5 15.5 19.2 18l2.3.8-2.3.8-.7 2.4-.7-2.4-2.3-.8 2.3-.8z" /></>,
  proprieta: <><path d="M4 7h10M18 7h2M4 12h4M12 12h8M4 17h10M18 17h2" /><circle cx="16" cy="7" r="2" /><circle cx="10" cy="12" r="2" /><circle cx="16" cy="17" r="2" /></>,
  libreria: <><path d="m12 3 9 5-9 5-9-5z" /><path d="m3 13 9 5 9-5" /><path d="m3 17 9 4 9-4" /></>,
  proxy: <><rect x="3" y="5" width="18" height="14" rx="1.5" /><path d="M8 9.5h8M8 12.5h8M8 15.5h4" /></>,
  spunta: <path d="m5 12.5 4.5 4.5L19 7" />,
  attesa: <><circle cx="12" cy="12" r="8" opacity=".3" /><path d="M20 12a8 8 0 0 0-8-8" /></>,

  // --- effetti video. Il nome della chiave e' quello dell'effetto nel
  // backend, cosi' il catalogo non ha bisogno di una tabella di conversione.
  color: <><circle cx="12" cy="12" r="8" /><path d="M12 4a8 8 0 0 1 0 16z" fill="currentColor" stroke="none" /></>,
  colorbalance: <><circle cx="9" cy="10" r="5" /><circle cx="15" cy="10" r="5" /><circle cx="12" cy="15" r="5" /></>,
  temperature: <><path d="M12 4v9" /><circle cx="12" cy="17" r="3.5" /><path d="M17 6h3M17 10h3" /></>,
  curves: <><rect x="4" y="4" width="16" height="16" rx="1.5" /><path d="M4 20c5 0 3-8 8-8s3 8 8 8" /></>,
  lut: <><path d="m12 3 8 4.5v9L12 21l-8-4.5v-9z" /><path d="M12 12v9M12 12l8-4.5M12 12 4 7.5" /></>,
  blur: <><circle cx="12" cy="12" r="3" /><circle cx="12" cy="12" r="6.5" opacity=".55" /><circle cx="12" cy="12" r="9.5" opacity=".25" /></>,
  sharpen: <><path d="M4 18h16" /><path d="m8 18 4-11 4 11" /></>,
  glow: <><circle cx="12" cy="12" r="4" /><path d="M12 3v2.5M12 18.5V21M3 12h2.5M18.5 12H21M5.6 5.6l1.8 1.8M16.6 16.6l1.8 1.8M18.4 5.6l-1.8 1.8M7.4 16.6l-1.8 1.8" /></>,
  vignette: <><rect x="3" y="5" width="18" height="14" rx="1.5" /><circle cx="12" cy="12" r="5" opacity=".55" /></>,
  grain: <><rect x="3" y="5" width="18" height="14" rx="1.5" /><path d="M7 9h.01M11 8h.01M15 10h.01M9 13h.01M13 12h.01M17 14h.01M8 16h.01M12 16h.01M16 17h.01" /></>,
  denoise: <><path d="M4 12h3l2-4 2 8 2-6 2 4h5" /><path d="M18 6h.01M20 9h.01" /></>,
  chromakey: <><rect x="3" y="5" width="18" height="14" rx="1.5" /><path d="M12 9c1.8 2 2.8 3.4 2.8 4.6a2.8 2.8 0 0 1-5.6 0C9.2 12.4 10.2 11 12 9z" /></>,
  crop: <><path d="M7 3v14h14" /><path d="M3 7h14v14" /></>,
  pixelate: <><rect x="4" y="4" width="7" height="7" /><rect x="13" y="4" width="7" height="7" opacity=".45" /><rect x="4" y="13" width="7" height="7" opacity=".45" /><rect x="13" y="13" width="7" height="7" /></>,
  mirror: <><path d="M12 3v18" strokeDasharray="2 2" /><path d="M9 7 4 12l5 5z" /><path d="m15 7 5 5-5 5z" opacity=".45" /></>,
  stabilize: <><circle cx="12" cy="12" r="3" /><path d="M4 8V5.5A1.5 1.5 0 0 1 5.5 4H8M16 4h2.5A1.5 1.5 0 0 1 20 5.5V8M20 16v2.5a1.5 1.5 0 0 1-1.5 1.5H16M8 20H5.5A1.5 1.5 0 0 1 4 18.5V16" /></>,
  motionblur: <><circle cx="16" cy="12" r="3.5" /><path d="M3 10h6M2 14h7M5 12h5" opacity=".7" /></>,

  // --- effetti audio
  eq3: <><path d="M7 4v16M12 4v16M17 4v16" /><circle cx="7" cy="9" r="2" /><circle cx="12" cy="15" r="2" /><circle cx="17" cy="11" r="2" /></>,
  compressor: <><path d="M3 6h18M3 18h18" /><path d="M6 12h2l1.5-3 2 6 2-4 1.5 1h3" /></>,
  limiter: <><path d="M3 7h18" /><path d="M4 18h2l1.5-7 2 9 2-11 2 9 1.5-4h5" /></>,
  adenoise: <><path d="M3 12h4l2-5 2 10 2-7 2 2h5" /><path d="M19 5h.01M21 8h.01M17 4h.01" /></>,
  highpass: <><path d="M3 18c6 0 6-11 10-11h8" /><path d="M3 18h4" opacity=".5" /></>,
  lowpass: <><path d="M3 7h11c4 0 4 11 7 11" /><path d="M17 18h4" opacity=".5" /></>,
  echo: <><path d="M5 8v8" /><path d="M11 9.5v5" opacity=".7" /><path d="M16 11v2" opacity=".45" /><path d="M20 11.5v1" opacity=".3" /></>,
  reverb: <><circle cx="12" cy="12" r="2" /><path d="M7.5 8.5a5 5 0 0 0 0 7M16.5 8.5a5 5 0 0 1 0 7" /><path d="M4.5 5.5a9 9 0 0 0 0 13M19.5 5.5a9 9 0 0 1 0 13" opacity=".45" /></>,
  pitch: <><circle cx="8" cy="17" r="3" /><path d="M11 17V6l8-2v11" /><circle cx="16" cy="15" r="3" /></>,
  gate: <><path d="M3 12h5l1-6 2 12 2-9 1 3h7" /><path d="M8 4v16M17 4v16" opacity=".45" strokeDasharray="2 2" /></>,
  dynnorm: <><path d="M3 16h3l2-6 2 9 2-11 2 8 2-4h6" /><path d="M12 3v3M9 5l3-3 3 3" opacity=".6" /></>,

  // --- transizioni. Il nome e' quello del tipo nel backend.
  dissolve: <><rect x="3" y="6" width="12" height="12" rx="1.5" /><rect x="9" y="6" width="12" height="12" rx="1.5" opacity=".45" /></>,
  iris: <><rect x="3" y="5" width="18" height="14" rx="1.5" /><circle cx="12" cy="12" r="2.5" /><circle cx="12" cy="12" r="5.5" opacity=".45" /></>,
  wipe_right: <><rect x="3" y="5" width="18" height="14" rx="1.5" /><path d="M11 5v14" /><path d="m14 9.5 3 2.5-3 2.5" /></>,
  wipe_left: <><rect x="3" y="5" width="18" height="14" rx="1.5" /><path d="M13 5v14" /><path d="m10 9.5-3 2.5 3 2.5" /></>,
  wipe_down: <><rect x="3" y="5" width="18" height="14" rx="1.5" /><path d="M3 11h18" /><path d="m9.5 14 2.5 3 2.5-3" /></>,
  wipe_up: <><rect x="3" y="5" width="18" height="14" rx="1.5" /><path d="M3 13h18" /><path d="m9.5 10 2.5-3 2.5 3" /></>,
  slide_left: <><rect x="3" y="5" width="18" height="14" rx="1.5" opacity=".4" /><path d="M13 5h6.5A1.5 1.5 0 0 1 21 6.5v11a1.5 1.5 0 0 1-1.5 1.5H13z" /><path d="m9 12-4 0m1.5-2-2 2 2 2" /></>,
  slide_right: <><rect x="3" y="5" width="18" height="14" rx="1.5" opacity=".4" /><path d="M11 5H4.5A1.5 1.5 0 0 0 3 6.5v11A1.5 1.5 0 0 0 4.5 19H11z" /><path d="m15 12 4 0m-1.5-2 2 2-2 2" /></>,
  slide_up: <><rect x="3" y="5" width="18" height="14" rx="1.5" opacity=".4" /><path d="M3 13h18v4.5a1.5 1.5 0 0 1-1.5 1.5h-15A1.5 1.5 0 0 1 3 17.5z" /><path d="M12 11V7m-2 1.5L12 6l2 2.5" /></>,
  slide_down: <><rect x="3" y="5" width="18" height="14" rx="1.5" opacity=".4" /><path d="M4.5 5h15A1.5 1.5 0 0 1 21 6.5V11H3V6.5A1.5 1.5 0 0 1 4.5 5z" /><path d="M12 13v4m-2-1.5 2 2.5 2-2.5" /></>,

  // --- look e catene audio della libreria
  cinema_teal_orange: <><circle cx="12" cy="12" r="8" /><path d="M12 4a8 8 0 0 1 0 16z" fill="currentColor" stroke="none" opacity=".55" /><path d="M12 4v16" /></>,
  bianco_e_nero: <><circle cx="9" cy="12" r="6" /><circle cx="15" cy="12" r="6" fill="currentColor" stroke="none" opacity=".55" /></>,
  bn_contrastato: <><rect x="3" y="5" width="18" height="14" rx="1.5" /><path d="M3 12h18" /><path d="M3 5h9v7H3z" fill="currentColor" stroke="none" opacity=".7" /></>,
  caldo_tramonto: <><path d="M3 18h18" /><circle cx="12" cy="13" r="4" /><path d="M12 4v2M5.5 6.5 7 8M18.5 6.5 17 8" /></>,
  freddo_notturno: <><path d="M17 13.5A6.5 6.5 0 0 1 10.5 7 6.5 6.5 0 1 0 17 13.5z" /><path d="M18 5.5h.01M20 9h.01" /></>,
  sbiadito_pellicola: <><rect x="3" y="6" width="18" height="12" rx="1.5" /><path d="M3 9h3M3 12h3M3 15h3M18 9h3M18 12h3M18 15h3" opacity=".6" /></>,
  vhs: <><rect x="2.5" y="7" width="19" height="10" rx="1.5" /><circle cx="9" cy="12" r="2" /><circle cx="15" cy="12" r="2" /><path d="M6 15.5h12" opacity=".5" /></>,
  sogno: <><circle cx="12" cy="12" r="4" opacity=".55" /><circle cx="12" cy="12" r="7.5" opacity=".3" /><path d="M18 4.5 18.7 6.5 20.7 7.2 18.7 7.9 18 9.9 17.3 7.9 15.3 7.2 17.3 6.5z" /></>,
  pulisci_ripresa: <><path d="M4 20 14 10" /><path d="m12 4 1.2 3.3L16.5 8.5 13.2 9.7 12 13l-1.2-3.3L7.5 8.5l3.3-1.2z" /><path d="m17 14 .8 2.2 2.2.8-2.2.8-.8 2.2-.8-2.2-2.2-.8 2.2-.8z" opacity=".6" /></>,
  voce_pulita: <><rect x="9" y="3" width="6" height="11" rx="3" /><path d="M5.5 11.5a6.5 6.5 0 0 0 13 0" /><path d="M12 18v3" /></>,
  voce_radio: <><rect x="10" y="3" width="4" height="9" rx="2" /><path d="M7 10.5a5 5 0 0 0 10 0" /><path d="M12 15.5v2.5" /><path d="M4.5 5.5a9 9 0 0 0 0 9M19.5 5.5a9 9 0 0 1 0 9" opacity=".5" /></>,
  telefono: <><path d="M7 3.5 9.5 8 7.5 10a11 11 0 0 0 6 6l2-2 4.5 2.5v3a1.5 1.5 0 0 1-1.6 1.5C9.6 20.4 3.6 14.4 3 5.1A1.5 1.5 0 0 1 4.5 3.5z" /></>,
  musica_sotto_voce: <><circle cx="7" cy="16" r="2.5" /><path d="M9.5 16V7l7-2v9" /><circle cx="14" cy="14" r="2.5" /><path d="M20 8v6m-2-2 2 2.5 2-2.5" opacity=".6" /></>,
  volume_costante: <><path d="M3 8h18M3 16h18" opacity=".5" /><path d="M4 12h2l1.5-3 2 6 2-5 2 4 1.5-2h5" /></>,
}

/**
 * Concetti che si ripetono con nomi diversi: il look "vignettatura" e
 * l'effetto "vignette" sono la stessa cosa, e disegnarli due volte vorrebbe
 * dire due glifi che col tempo divergono.
 */
const ALIAS = {
  vignettatura: 'vignette',
  specchia: 'mirror',
  stabilizza: 'stabilize',
  nitido: 'sharpen',
  censura: 'pixelate',
  eco: 'echo',
  sala_grande: 'reverb',
}

export default function Icon({ name, size = 16, className = '', title }) {
  const d = paths[name] || paths[ALIAS[name]]
  if (!d) return null
  return (
    <svg className={`ico ${className}`} width={size} height={size} viewBox="0 0 24 24"
      fill="none" stroke="currentColor" strokeWidth="1.7"
      strokeLinecap="round" strokeLinejoin="round" aria-hidden={title ? undefined : true}
      focusable="false" role={title ? 'img' : undefined}>
      {title && <title>{title}</title>}
      {d}
    </svg>
  )
}
