// The cast, ported from design/prototype: SVG strings with CSS-class motion (see proto.css). Static markup only,
// no user data ever goes into these strings.
/* eslint-disable */
// @ts-nocheck
export const C = {
  clerk(pose = "idle", size = 160, extra = "") {
    const h = Math.round(size * 1.3);
    const happy = pose === "wave" || pose === "cheer";
    const eyes = happy
      ? '<path d="M76 78 Q84 68 92 78" stroke="#9CC3FF" stroke-width="5" fill="none" stroke-linecap="round"/><path d="M108 78 Q116 68 124 78" stroke="#9CC3FF" stroke-width="5" fill="none" stroke-linecap="round"/>'
      : pose === "think"
      ? '<g class="blink"><circle cx="84" cy="76" r="7" fill="#9CC3FF"/><circle cx="116" cy="72" r="9" fill="#9CC3FF"/></g>'
      : '<g class="blink"><circle cx="84" cy="76" r="7" fill="#9CC3FF"/><circle cx="116" cy="76" r="7" fill="#9CC3FF"/></g>';
    const mouth = pose === "sheepish"
      ? '<path d="M88 96 Q100 88 112 96" stroke="#9CC3FF" stroke-width="4" fill="none" stroke-linecap="round"/>'
      : pose === "stop" || pose === "think"
      ? '<path d="M90 94 L110 94" stroke="#9CC3FF" stroke-width="4" stroke-linecap="round"/>'
      : '<path d="M86 90 Q100 102 114 90" stroke="#9CC3FF" stroke-width="4" fill="none" stroke-linecap="round"/>';
    const leftArm = pose === "cheer"
      ? '<rect x="18" y="70" width="26" height="72" rx="13" fill="#4B3BD6" transform="rotate(-24 31 106)"/>'
      : '<rect x="26" y="132" width="26" height="72" rx="13" fill="#4B3BD6"/>';
    let rightArm = '<rect x="148" y="132" width="26" height="72" rx="13" fill="#4B3BD6"/>';
    if (pose === "wave") rightArm = '<g class="wave"><rect x="150" y="62" width="26" height="72" rx="13" fill="#4B3BD6" transform="rotate(24 163 98)"/><circle cx="178" cy="58" r="14" fill="#4B3BD6"/></g>';
    if (pose === "stop") rightArm = '<rect x="152" y="66" width="26" height="72" rx="13" fill="#4B3BD6" transform="rotate(14 165 102)"/><circle cx="174" cy="62" r="15" fill="#4B3BD6"/>';
    if (pose === "cheer") rightArm = '<rect x="156" y="70" width="26" height="72" rx="13" fill="#4B3BD6" transform="rotate(24 169 106)"/>';
    if (pose === "magnify") rightArm = '<rect x="150" y="96" width="26" height="64" rx="13" fill="#4B3BD6" transform="rotate(30 163 128)"/><line x1="168" y1="92" x2="182" y2="112" stroke="#1E1B4B" stroke-width="9" stroke-linecap="round"/><circle cx="158" cy="76" r="24" fill="#DCE8FF" fill-opacity=".75" stroke="#1E1B4B" stroke-width="6"/>';
    const q = pose === "think" ? '<circle cx="178" cy="26" r="20" fill="#2F64E0"/><path d="M171 20 Q178 10 185 18 Q188 26 178 28 L178 34" stroke="#fff" stroke-width="4" fill="none" stroke-linecap="round"/><circle cx="178" cy="41" r="2.5" fill="#fff"/>' : "";
    const tilt = pose === "think" ? ' transform="rotate(-8 100 80)"' : "";
    return `<svg viewBox="0 0 200 260" width="${size}" height="${h}" role="img" aria-label="The AI clerk" ${extra}><ellipse cx="100" cy="250" rx="66" ry="8" fill="#D6D0FF"/><g class="bob"><rect x="52" y="122" width="96" height="112" rx="30" fill="#6D5BFF"/><rect x="80" y="148" width="40" height="24" rx="6" fill="#fff"/><rect x="86" y="157" width="28" height="6" rx="3" fill="#6D5BFF"/>${leftArm}${rightArm}<rect x="70" y="228" width="22" height="18" rx="8" fill="#4B3BD6"/><rect x="108" y="228" width="22" height="18" rx="8" fill="#4B3BD6"/><g${tilt}><g class="antenna"><line x1="100" y1="34" x2="100" y2="14" stroke="#8B7DFF" stroke-width="6" stroke-linecap="round"/><circle cx="100" cy="12" r="8" fill="#9CC3FF"/></g><rect x="44" y="32" width="112" height="92" rx="36" fill="#8B7DFF"/><rect x="60" y="52" width="80" height="52" rx="22" fill="#1E1B4B"/>${eyes}${mouth}</g>${q}</g></svg>`;
  },
  con(mood = "smirk", size = 140) {
    const h = Math.round(size * 1.3);
    const mouth = mood === "grin" ? '<path d="M84 106 Q100 122 116 106" stroke="#C7BFFF" stroke-width="4" fill="none" stroke-linecap="round"/>'
      : mood === "unsure" ? '<path d="M88 110 L112 110" stroke="#C7BFFF" stroke-width="4" stroke-linecap="round"/>'
      : mood === "defeated" ? '<path d="M88 112 Q100 102 112 112" stroke="#C7BFFF" stroke-width="4" fill="none" stroke-linecap="round"/>'
      : '<path d="M88 110 Q102 116 114 104" stroke="#C7BFFF" stroke-width="3" fill="none" stroke-linecap="round"/>';
    return `<svg viewBox="0 0 200 260" width="${size}" height="${h}" role="img" aria-label="The con artist"><ellipse cx="100" cy="250" rx="66" ry="8" fill="#D6D0FF"/><g class="sway"><path d="M58 124 L142 124 L164 242 L36 242 Z" fill="#3B2A73"/><path d="M100 124 L78 182 L100 166 L122 182 Z" fill="#251A52"/><rect x="140" y="140" width="50" height="36" rx="6" fill="#fff" stroke="#B8AEFF" stroke-width="3" transform="rotate(-12 165 158)"/><circle cx="100" cy="92" r="36" fill="#55449C"/><rect x="64" y="78" width="72" height="18" rx="9" fill="#1E1B4B"/><g class="blink"><circle cx="86" cy="87" r="4" fill="#C7BFFF"/><circle cx="114" cy="87" r="4" fill="#C7BFFF"/></g>${mouth}<ellipse cx="100" cy="62" rx="60" ry="10" fill="#1E1B4B"/><rect x="70" y="26" width="60" height="38" rx="10" fill="#1E1B4B"/><rect x="70" y="50" width="60" height="8" fill="#7C5CFF"/></g></svg>`;
  },
  person(kind = "owner", size = 140) {
    const h = Math.round(size * 1.3);
    const body = kind === "owner" ? "#2F64E0" : "#8B7DFF";
    const hair = kind === "owner"
      ? '<path d="M60 84 Q62 44 100 44 Q140 44 140 84 Q128 62 100 62 Q72 62 60 84 Z" fill="#2B2560"/>'
      : '<circle cx="100" cy="44" r="16" fill="#2B2560"/><path d="M60 90 Q60 50 100 50 Q140 50 140 90 Q130 66 100 66 Q70 66 60 90 Z" fill="#2B2560"/>';
    const prop = kind === "owner"
      ? '<path d="M92 134 L108 134 L104 190 L100 198 L96 190 Z" fill="#1E1B4B"/>'
      : '<rect x="112" y="150" width="44" height="58" rx="6" fill="#fff" stroke="#4B3BD6" stroke-width="4"/><rect x="122" y="144" width="24" height="10" rx="4" fill="#4B3BD6"/><path d="M120 170 h28 M120 182 h22" stroke="#C7BFFF" stroke-width="4" stroke-linecap="round"/>';
    return `<svg viewBox="0 0 200 260" width="${size}" height="${h}" role="img" aria-label="${kind === "owner" ? "The owner" : "The finance manager"}"><ellipse cx="100" cy="250" rx="66" ry="8" fill="#D6D0FF"/><g class="bob"><path d="M50 240 Q50 132 100 132 Q150 132 150 240 Z" fill="${body}"/>${prop}<circle cx="100" cy="88" r="40" fill="#F2DFD3"/>${hair}<g class="blink"><circle cx="86" cy="92" r="4" fill="#1E1B4B"/><circle cx="114" cy="92" r="4" fill="#1E1B4B"/></g><path d="M90 108 Q100 114 110 108" stroke="#1E1B4B" stroke-width="3" fill="none" stroke-linecap="round"/></g></svg>`;
  },
  supervisor(size = 120) {
    const h = Math.round(size * 1.3);
    return `<svg viewBox="0 0 200 260" width="${size}" height="${h}" role="img" aria-label="The supervisor, a blue robot holding a stamp"><ellipse cx="100" cy="250" rx="66" ry="8" fill="#BFD3FF"/><g class="bob"><rect x="52" y="122" width="96" height="112" rx="24" fill="#2F64E0"/><rect x="26" y="132" width="26" height="72" rx="13" fill="#1F4CB8"/><rect x="148" y="126" width="26" height="60" rx="13" fill="#1F4CB8"/><rect x="136" y="180" width="52" height="22" rx="6" fill="#6D5BFF"/><rect x="150" y="202" width="24" height="12" rx="3" fill="#4B3BD6"/><rect x="46" y="40" width="108" height="86" rx="22" fill="#3E7BFA"/><rect x="62" y="60" width="76" height="46" rx="14" fill="#1E1B4B"/><g class="blink"><rect x="74" y="78" width="18" height="6" rx="3" fill="#9CC3FF"/><rect x="108" y="78" width="18" height="6" rx="3" fill="#9CC3FF"/></g><path d="M44 46 Q100 4 156 46 Z" fill="#1E1B4B"/><rect x="38" y="42" width="124" height="10" rx="5" fill="#1E1B4B"/></g></svg>`;
  },
  vault(size = 110) {
    return `<svg viewBox="0 0 200 200" width="${size}" height="${size}" role="img" aria-label="The contract vault"><rect x="16" y="16" width="168" height="168" rx="28" fill="#4B3BD6"/><g class="sway"><circle cx="100" cy="100" r="56" fill="#6D5BFF" stroke="#B8AEFF" stroke-width="8"/><path d="M100 56 L100 144 M56 100 L144 100" stroke="#E4E0FF" stroke-width="8" stroke-linecap="round"/><circle cx="100" cy="100" r="16" fill="#E4E0FF"/></g><rect x="152" y="70" width="14" height="30" rx="6" fill="#B8AEFF"/></svg>`;
  },
  checklist(size = 96) {
    return `<svg viewBox="0 0 160 200" width="${size}" height="${Math.round(size * 1.25)}" role="img" aria-label="A checklist"><rect x="20" y="20" width="120" height="164" rx="14" fill="#fff" stroke="#8B7DFF" stroke-width="5"/><rect x="56" y="10" width="48" height="22" rx="8" fill="#4B3BD6"/><g stroke="#2F64E0" stroke-width="6" fill="none" stroke-linecap="round" stroke-linejoin="round"><path d="M38 60 l10 10 l18 -20"/><path d="M38 100 l10 10 l18 -20"/><path d="M38 140 l10 10 l18 -20"/></g><g fill="#DAD6FB"><rect x="76" y="58" width="48" height="8" rx="4"/><rect x="76" y="98" width="48" height="8" rx="4"/><rect x="76" y="138" width="48" height="8" rx="4"/></g></svg>`;
  },
  bank(size = 120) {
    return `<svg viewBox="0 0 240 220" width="${size}" height="${Math.round(size * .92)}" role="img" aria-label="A bank"><polygon points="20,70 120,16 220,70" fill="#4B3BD6"/><circle cx="120" cy="50" r="12" fill="#B8AEFF"/><rect x="30" y="70" width="180" height="14" fill="#6D5BFF"/><g fill="#B8AEFF"><rect x="44" y="92" width="22" height="90" rx="4"/><rect x="88" y="92" width="22" height="90" rx="4"/><rect x="132" y="92" width="22" height="90" rx="4"/><rect x="176" y="92" width="22" height="90" rx="4"/></g><rect x="24" y="182" width="192" height="20" rx="4" fill="#4B3BD6"/></svg>`;
  },
  mark(size = 34) {
    return `<svg viewBox="0 0 64 64" width="${size}" height="${size}" aria-hidden="true"><rect x="4" y="10" width="56" height="46" rx="18" fill="#8B7DFF"/><rect x="12" y="20" width="40" height="26" rx="11" fill="#1E1B4B"/><g class="blink"><circle cx="24" cy="33" r="4" fill="#9CC3FF"/><circle cx="40" cy="33" r="4" fill="#9CC3FF"/></g><circle cx="32" cy="5" r="4" fill="#9CC3FF"/></svg>`;
  },
};

export const ICON = {
  desk: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><rect x="3" y="4" width="18" height="12" rx="2"/><path d="M8 20h8M12 16v4"/></svg>',
  activity: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M3 12h4l3-8 4 16 3-8h4"/></svg>',
  risk: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M4 18a8 8 0 1 1 16 0"/><path d="M12 18l4-6"/></svg>',
  shield: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M12 3l8 3v6c0 5-3.5 8-8 9-4.5-1-8-4-8-9V6z"/></svg>',
  settings: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><circle cx="12" cy="12" r="3"/><path d="M19 12a7 7 0 0 0-.1-1.2l2-1.6-2-3.4-2.4 1a7 7 0 0 0-2-1.2L14 3h-4l-.5 2.6a7 7 0 0 0-2 1.2l-2.4-1-2 3.4 2 1.6A7 7 0 0 0 5 12c0 .4 0 .8.1 1.2l-2 1.6 2 3.4 2.4-1a7 7 0 0 0 2 1.2L10 21h4l.5-2.6a7 7 0 0 0 2-1.2l2.4 1 2-3.4-2-1.6c.1-.4.1-.8.1-1.2z"/></svg>',
  check: '<svg viewBox="0 0 24 24" width="18" height="18" fill="none" stroke="#9CC3FF" stroke-width="3" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M5 12l5 5 9-10"/></svg>',
  wallet: '<svg viewBox="0 0 24 24" width="26" height="26" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><rect x="3" y="6" width="18" height="13" rx="3"/><path d="M16 12h2M3 9l13-4"/></svg>',
  phone: '<svg viewBox="0 0 24 24" width="26" height="26" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" aria-hidden="true"><rect x="7" y="2" width="10" height="20" rx="2"/><path d="M11 18h2"/></svg>',
  key: '<svg viewBox="0 0 24 24" width="26" height="26" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><circle cx="8" cy="15" r="4"/><path d="M11 12l9-9M17 6l3 3"/></svg>',
  sliders: '<svg viewBox="0 0 24 24" width="18" height="18" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" aria-hidden="true"><path d="M4 6h10M18 6h2M4 12h4M12 12h8M4 18h12M20 18h0"/><circle cx="16" cy="6" r="2"/><circle cx="10" cy="12" r="2"/><circle cx="18" cy="18" r="2"/></svg>',
};

export function Art({ html, className }: { html: string; className?: string }) {
  return <span className={className} style={{ display: "inline-flex" }} dangerouslySetInnerHTML={{ __html: html }} />;
}
