// Page behaviour (entrance, reveal, header, nav glow, copy button) and the
// Discord demo. The .js class gates every hidden state in CSS, so without this
// file the page is static and fully readable; only the demo needs it.
document.documentElement.classList.add('js');

// ---------- header ----------

const header = document.getElementById('top-bar');
const syncHeader = () => header.classList.toggle('scrolled', window.scrollY > 8);
syncHeader();
window.addEventListener('scroll', syncHeader, { passive: true });

// ---------- Discord rendering ----------
//
// Strings below are in the exact shapes the bot's formatters produce
// (shared/formatters.py, dashboard_service.py, the platform stream_embeds.py
// files, cogs/sabnzbd.py). Change the bot's output, change them here too.

const TWEMOJI = 'https://cdn.jsdelivr.net/gh/jdecked/twemoji@15.1.0/assets/svg/';
// Emoji Discord draws as Twemoji: anything with emoji presentation, or a text
// symbol forced to emoji by VS16. A bare ▶ stays text, as it does in Discord.
const EMOJI = /(?:\p{Emoji_Presentation}|\p{Extended_Pictographic}\uFE0F)[\u{1F3FB}-\u{1F3FF}]?(?:\u200D(?:\p{Emoji_Presentation}|\p{Extended_Pictographic}\uFE0F?))*/gu;

const esc = (s) => String(s).replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;').replace(/"/g, '&quot;');

const twemojiURL = (emoji) => {
  // Twemoji drops VS16 from file names unless the emoji is a ZWJ sequence.
  const chars = emoji.includes('\u200D') ? [...emoji] : [...emoji].filter((c) => c !== '\uFE0F');
  return `${TWEMOJI}${chars.map((c) => c.codePointAt(0).toString(16)).join('-')}.svg`;
};

// Replace every emoji with Twemoji, inside code too. Discord leaves emoji in
// code to the system font, but a visitor without a colour emoji font would
// then see empty boxes in front of every stream; drawn images always show.
const emojify = (html) => {
  let inCode = 0;
  return html.split(/(<[^>]+>)/).map((part) => {
    if (part.startsWith('<')) {
      if (/^<(pre|code)\b/.test(part)) inCode++;
      else if (/^<\/(pre|code)>/.test(part)) inCode--;
      return part;
    }
    const cls = inCode ? 'emoji in-code' : 'emoji';
    return part.replace(EMOJI, (e) => `<img class="${cls}" alt="${e}" draggable="false" src="${twemojiURL(e)}">`);
  }).join('');
};

const clock = (date) => date.toLocaleTimeString('en-US', { hour: 'numeric', minute: '2-digit' });
const clock24 = (date) => `${String(date.getHours()).padStart(2, '0')}:${String(date.getMinutes()).padStart(2, '0')}`;
const today = () => `Today at ${clock(new Date())}`;

// Discord timestamp markup <t:unix:style>, rendered in the reader's zone.
const discordTime = (unix, style) => {
  const date = new Date(unix * 1000);
  if (style === 'R') {
    const minutes = Math.max(1, Math.round((Date.now() - date) / 60000));
    return `${minutes} minute${minutes === 1 ? '' : 's'} ago`;
  }
  return `${date.toLocaleDateString('en-US', { month: 'long', day: 'numeric', year: 'numeric' })} ${clock(date)}`;
};

// The slice of Discord markdown the bot uses: code blocks (plain and ansi),
// inline code, bold, italic, links and timestamps.
// The bot's progress bars are ▓ for done and ░ for to go. Shade glyphs blur
// into the same grey at normal pixel density, so each run is repainted with
// the pixel pattern Discord shows (see .bar-on/.bar-off). The glyphs stay in
// the text, transparent: the block keeps its exact column grid and copies as
// the bot wrote it.
const bars = (code) => code
  .replace(/▓+/g, (run) => `<span class="bar-on">${run}</span>`)
  .replace(/░+/g, (run) => `<span class="bar-off">${run}</span>`);

const md = (text) => {
  const stash = [];
  const keep = (html) => `\u0000${stash.push(html) - 1}\u0000`;
  let s = esc(text);
  // The bot wraps each stream block in ** **; Discord drops the bold there.
  s = s.replace(/(?:\*\*)?```(?:([a-z]+)\n)?([\s\S]*?)```(?:\*\*)?/g, (_, lang, body) => {
    let code = body.replace(/^\n/, '').replace(/\n$/, '');
    // Discord's ansi blocks: 0/1 is normal/bold, 3x the foreground colour.
    if (lang === 'ansi') code = code.replace(/\x1b\[([01]);(3\d)m(.*?)\x1b\[0m/g, (_, b, fg, t) => `<span class="ansi-${fg}${b === '1' ? ' ansi-b' : ''}">${t}</span>`);
    return keep(`<pre><code>${bars(code)}</code></pre>`);
  });
  s = s.replace(/`([^`\n]+)`/g, (_, c) => keep(`<code class="icode">${bars(c)}</code>`));
  s = s.replace(/&lt;t:(\d+):([fR])&gt;/g, (_, t, st) => keep(`<span class="dts">${discordTime(+t, st)}</span>`));
  s = s.replace(/\[([^\]]+)\]\(([^)]+)\)/g, '<a href="$2" rel="noopener" target="_blank">$1</a>');
  s = s.replace(/\*\*([^*]+)\*\*/g, '<strong>$1</strong>');
  s = s.replace(/\*([^*]+)\*/g, '<em>$1</em>');
  // Consecutive "1. " lines become a real list, as Discord renders them.
  s = s.replace(/(?:^|\n)((?:\d+\. .*(?:\n|$))+)/g, (block, items) => {
    const lines = items.trim().split('\n');
    const lead = block.startsWith('\n') ? '\n' : '';
    return `${lead}<ol start="${parseInt(lines[0], 10)}">${lines.map((l) => `<li>${l.replace(/^\d+\. /, '')}</li>`).join('')}</ol>`;
  });
  return s.replace(/\u0000(\d+)\u0000/g, (_, i) => stash[i]);
};

// Inline fields sit three to a row. Discord assigns the spans in its client:
// one field fills the row, two split it, three take a third each.
const SPANS = [[], ['1 / 13'], ['1 / 7', '7 / 13'], ['1 / 5', '5 / 9', '9 / 13']];
const fieldsHTML = (fields) => {
  let out = '';
  let run = [];
  const field = (f, span) => `<div class="field" style="grid-column:${span}">`
    + `<div class="field-name">${md(f.name)}</div><div class="field-value">${md(f.value)}</div></div>`;
  const flush = () => {
    for (let i = 0; i < run.length; i += 3) {
      const row = run.slice(i, i + 3);
      row.forEach((f, j) => { out += field(f, SPANS[row.length][j]); });
    }
    run = [];
  };
  fields.forEach((f) => {
    if (f.inline) run.push(f);
    else { flush(); out += field(f, '1 / 13'); }
  });
  flush();
  return `<div class="embed-fields">${out}</div>`;
};

const embedHTML = (e) => {
  const parts = [];
  if (e.author) parts.push(`<div class="embed-author">${e.author.icon || ''}<span>${esc(e.author.name)}</span></div>`);
  if (e.title) {
    const title = md(e.title);
    parts.push(`<div class="embed-title">${e.url ? `<a href="${e.url}" rel="noopener" target="_blank">${title}</a>` : title}</div>`);
  }
  if (e.desc) parts.push(`<div class="embed-desc">${md(e.desc)}</div>`);
  if (e.fields?.length) parts.push(fieldsHTML(e.fields));
  if (e.image) parts.push(`<div class="embed-image">${e.image}</div>`);
  if (e.footer) {
    const stamp = e.timestamp ? `<span class="sep">•</span><span>${today()}</span>` : '';
    parts.push(`<div class="embed-footer">${e.footer.icon || ''}<span>${esc(e.footer.text)}</span>${stamp}</div>`);
  }
  const thumb = e.thumb ? `<div class="embed-thumb">${e.thumb}</div>` : '';
  return `<article class="embed" style="--c:${e.color}"><div class="embed-grid${e.thumb ? ' has-thumb' : ''}">${parts.join('')}${thumb}</div></article>`;
};

const buttonHTML = (b, live) => {
  const emoji = b.emoji ? `${b.emoji}` : '';
  const label = `${emoji}${b.label ? `<span>${esc(b.label)}</span>` : ''}`;
  if (b.style === 'link') {
    return `<a class="btn link" href="${b.url}" rel="noopener" target="_blank">${label}<svg aria-hidden="true"><use href="#d-link"/></svg></a>`;
  }
  const attrs = live && b.action ? ` data-action="${b.action}"` : ' tabindex="-1"';
  return `<button type="button" class="btn ${b.style}"${attrs}${b.disabled ? ' disabled' : ''}>${label}</button>`;
};
const rowsHTML = (rows, live) => (rows || []).map((row) => `<div class="row">${row.map((b) => buttonHTML(b, live)).join('')}</div>`).join('');

// The bot's profile picture: the logo on a full-bleed tile, which Discord crops round.
const BOT_AVATAR = '<img class="dc-avatar bot msg-avatar" src="avatar.svg" alt="">';

const messageHTML = (m) => {
  const body = m.thinking
    ? '<div class="thinking">MediaWatch is thinking<i></i><i></i><i></i></div>'
    : `${m.text ? `<div class="msg-text">${md(m.text)}</div>` : ''}${(m.embeds || []).map(embedHTML).join('')}${rowsHTML(m.rows, true)}`;
  // Ephemeral answers to a button point back at the message the button sits on.
  const reply = m.eph
    ? '<div class="msg-reply"><img class="dc-avatar bot reply-avatar" src="avatar.svg" alt="">'
      + '<span class="msg-tag">App</span><b>MediaWatch</b><i>Click to see attachment</i><svg class="reply-icon" width="20" height="20" aria-hidden="true"><use href="#d-image"/></svg></div>'
    : '';
  const note = m.eph
    ? `<div class="eph-note"><svg width="16" height="16" aria-hidden="true"><use href="#d-eye"/></svg>Only you can see this • <button type="button" data-action="dismiss">Dismiss message</button></div>`
    : '';
  return emojify(`${reply}${BOT_AVATAR}<div class="msg-head"><span class="msg-user">MediaWatch</span><span class="msg-tag">App</span>`
    + `<span class="msg-ts">${m.time}</span></div>${body}${note}`);
};

// ---------- mock data ----------

// The dashboard's icon_url is whatever image the server owner sets. The demo
// uses a neutral homelab glyph instead of any platform's logo, which are
// trademarks; the tint alone says which platform the demo is showing.
const SERVER_GLYPH = '<svg viewBox="0 0 24 24" width="58%" height="58%" aria-hidden="true" fill="none" stroke="currentColor" stroke-width="1.9" stroke-linecap="round">'
  + '<rect x="3.5" y="4" width="17" height="6.5" rx="2"/><rect x="3.5" y="13.5" width="17" height="6.5" rx="2"/>'
  + '<path d="M7.5 7.25h.01M7.5 16.75h.01M11 7.25h5.5M11 16.75h5.5"/></svg>';
const icon = (platform, size) => `<span class="ico ${platform}" style="width:${size}px;height:${size}px;border-radius:50%">${SERVER_GLYPH}</span>`;
const userIcon = (name) => `<span class="ico user" style="width:20px;height:20px;border-radius:50%">${esc(name[0])}</span>`;
const logoTile = (platform) => `<span class="logo-tile ${platform}">${SERVER_GLYPH}</span>`;
// Posters are drawn for the demo (landing/posters/), not the studios' artwork.
const poster = (s) => `<img class="poster" src="posters/${s.posterFile}" width="54" height="80" alt="">`;

const DASHBOARD_NAME = 'Homelab';
const COLOR = {
  green: '#2ecc71', red: '#e74c3c', orange: '#e67e22', blue: '#3498db', gold: '#f1c40f', purple: '#9b59b6',
  plex: '#e5a00d', jellyfin: '#00a4dc',
};

// Short display names, ordered so each row of three reads as one group: films
// on the first row, TV on the second. The episode tile is always named
// "{library} {episode_label}", hence "TV" rather than "TV Shows".
const LIBRARIES = {
  plex: [
    { name: 'Movies', emoji: '🎥', count: 2938 },
    { name: 'Movies 4K', emoji: '🎥', count: 346 },
    { name: 'Docs', emoji: '📚', count: 187 },
    { name: 'TV', emoji: '📺', count: 412, episodes: 21980 },
  ],
  jellyfin: [
    { name: 'Movies', emoji: '🎥', count: 2938 },
    { name: 'Music', emoji: '🎵', count: 1204 },
    { name: 'Docs', emoji: '📚', count: 187 },
    { name: 'TV', emoji: '📺', count: 412, episodes: 21980 },
  ],
};

// The three viewers: film and TV characters from one story, a different
// story on every page load. Every name stays at 12 characters or fewer, the
// length the bot keeps in a button label before it cuts to "...".
const CREWS = [
  ['Walter White', 'Saul Goodman', 'Gus Fring'],
  ['Han Solo', 'Leia Organa', 'Darth Vader'],
  ['Gandalf', 'Samwise', 'Aragorn'],
  ['Harry Potter', 'Hermione', 'Ron Weasley'],
  ['Neo', 'Trinity', 'Morpheus'],
  ['Chandler', 'Monica', 'Joey'],
  ['Dwight', 'Jim Halpert', 'Pam Beesly'],
  ['Marty McFly', 'Doc Brown', 'Biff Tannen'],
  ['Vincent Vega', 'Jules', 'Mia Wallace'],
  ['Eleven', 'Hopper', 'Dustin'],
  ['Jon Snow', 'Arya Stark', 'Tyrion'],
  ['Sherlock', 'Dr. Watson', 'Moriarty'],
  ['Elliot', 'Darlene', 'Mr. Robot'],
  ['Tony Soprano', 'Paulie', 'Christopher'],
  ['Homer', 'Marge', 'Bart'],
  ['Rick', 'Morty', 'Summer'],
  ['Tommy Shelby', 'Arthur', 'Polly'],
  ['Ted Lasso', 'Roy Kent', 'Keeley'],
  ['Homelander', 'Butcher', 'Starlight'],
  ['Maverick', 'Goose', 'Iceman'],
];
const CREW = CREWS[Math.floor(Math.random() * CREWS.length)];

// One set of streams; each carries what differs per platform.
const STREAMS = () => [
  {
    // The 2018 UHD release: HEVC 2160p with HDR10 and a DTS:X track, 117 min.
    id: 1, type: 'movie', title: 'The Big Lebowski', year: 1998, user: CREW[0], library: 'Movies 4K', emoji: '🎥',
    pos: 3812, dur: 7020, paused: false, transcode: false, quality: '4K',
    posterFile: 'the-big-lebowski.svg',
    summary: 'Jeffrey Lebowski, who prefers to be called the Dude, only wants his rug back after two thugs mistake him for a millionaire with the same name. Getting it back drags him and his bowling team into a kidnapping that makes less sense the closer they look.',
    rating: '8.1/10', director: 'Joel Coen', file: '61.84 GB • MKV', lang: 'English',
    plex: { player: 'Apple TV', playerFull: 'Living Room (Apple TV)', bitrate: '70.4 Mbps', bitrateDetail: '70.4 / 76.0 Mbps', conn: '🏠 LAN 🔒', res: '4K • HDR10', sub: 'German (SRT)' },
    jellyfin: { player: 'Infuse', playerFull: 'Infuse - Living Room', bitrate: '70.4 Mbps', bitrateDetail: '70.4 Mbps', conn: '🏠 LAN', res: '4K', sub: 'German (SUBRIP)' },
  },
  {
    // Season 1, episode 1: written by Sam Esmail, 65 min, first aired 2015.
    id: 2, type: 'episode', title: 'eps1.0_hellofriend.mov', show: 'Mr. Robot', episodeYear: 2015, season: 1, episode: 1, user: CREW[1], library: 'TV', emoji: '📺',
    pos: 2455, dur: 3900, paused: false, transcode: true, quality: '720p',
    posterFile: 'mr-robot.svg',
    summary: 'Elliot works in cybersecurity by day and hacks the people around him by night. Then a stranger who calls himself Mr. Robot asks for his help in bringing down the corporation his own employer is paid to protect.',
    rating: '9.2/10', writer: 'Sam Esmail', file: '4.12 GB • MKV',
    plex: {
      player: 'Plex Web', playerFull: 'Chrome (Plex Web)', bitrate: '4.0 Mbps', bitrateDetail: '8.9 / 4.0 Mbps', conn: '🌐 WAN 🔒', res: '1080p',
      transcoding: ['**Stream:** Transcode (`Throttled`)', '**Container:** Converting (`MKV` → `MPEGTS`)', '**Video:** Transcode (`HEVC (HW) 1080p` → `H264 (HW) 720p`)', '**Audio:** Transcode (`English - EAC3 5.1` → `AAC 2.0`)', '**Speed:** `3.1x`'],
    },
    jellyfin: {
      // Jellyfin reads resolution and the detail bitrate from the source file.
      player: 'Jellyfin Web', playerFull: 'Jellyfin Web - Chrome', quality: '1080p', bitrate: '4.0 Mbps', bitrateDetail: '8.9 Mbps', conn: '🌐 WAN', res: '1080p',
      transcoding: ['**Stream:** Transcode', '**Container:** Converting (`MKV` → `TS`)', '**Video:** Transcode (`HEVC 1080p` → `H264 (HW) 720p`)', '**Audio:** Transcode (`English - EAC3 5.1` → `AAC 2.0`)'],
    },
  },
  {
    // The 2018 UHD release: HDR10 and Dolby Vision, Dolby Atmos, 140 min.
    id: 3, type: 'movie', title: 'Ready Player One', year: 2018, user: CREW[2], library: 'Movies 4K', emoji: '🎥',
    pos: 5312, dur: 8400, paused: true, transcode: false, quality: '4K',
    posterFile: 'ready-player-one.svg',
    summary: 'In 2045 most people spend their days in the OASIS, a virtual universe. Its creator dies and leaves his fortune to whoever finds an egg he hid inside it, and Wade Watts joins the hunt against a company that wants the OASIS for itself.',
    rating: '7.4/10', director: 'Steven Spielberg', file: '57.36 GB • MKV', lang: 'English',
    plex: { player: 'Roku', playerFull: 'Bedroom (Roku)', bitrate: '55.9 Mbps', bitrateDetail: '55.9 / 60.0 Mbps', conn: '🏠 LAN 🔒', res: '4K • HDR10/DoVi', sub: '​' },
    jellyfin: { player: 'Roku', playerFull: 'Roku - Bedroom', bitrate: '55.9 Mbps', bitrateDetail: '55.9 Mbps', conn: '🏠 LAN', res: '4K', sub: '​' },
  },
];

const DOWNLOADS = [
  '**```📥 Furiosa.A.Mad.Max.Saga.2024.\n└─ [▓▓▓▓░░░░░░] 42.0% | 0:18:42 remaining\n └─ 📊 47.10 MB/s | Remaining: 38.00 GB```**',
  '**```📥 The.Penguin.S01E08.\n└─ [▓▓▓▓▓▓▓░░░] 71.3% | 0:04:10 remaining\n └─ 📊 47.10 MB/s | Remaining: 2.10 GB```**',
];

// ---------- formatters (ports of the bot's) ----------

const pad2 = (n) => String(n).padStart(2, '0');
const duration = (sec) => {
  sec = Math.floor(sec);
  const h = Math.floor(sec / 3600);
  const m = Math.floor((sec % 3600) / 60);
  const s = sec % 60;
  return h ? `${h}:${pad2(m)}:${pad2(s)}` : `${pad2(m)}:${pad2(s)}`;
};
const percent = (s) => Math.min(100, (s.pos / s.dur) * 100);
// format_progress_bar(): the stream details leave the percentage off, as the bot does.
const bar = (pct, showPercent = true) => {
  const filled = Math.floor(pct / 10);
  const cells = `[${'▓'.repeat(filled)}${'░'.repeat(10 - filled)}]`;
  return showPercent ? `${cells} ${pct.toFixed(1)}%` : cells;
};
const thousands = (n) => String(n).replace(/\B(?=(\d{3})+(?!\d))/g, '.');
const uptime = (minutes) => {
  const d = Math.floor(minutes / 1440);
  const rest = `${pad2(Math.floor((minutes % 1440) / 60))}:${pad2(minutes % 60)}`;
  return d ? `${d} ${d === 1 ? 'Day' : 'Days'} ${rest}` : rest;
};
const shortTitle = (s) => (s.type === 'movie' ? `${s.title} (${s.year})` : `${s.show} - S${pad2(s.season)}E${pad2(s.episode)}`);

const streamBlock = (s, platform) => {
  const p = s[platform];
  const progress = s.paused ? '⏸️' : bar(percent(s));
  return `**\`\`\`${s.emoji} ${shortTitle(s)} | ${s.user}\n└─ ${progress} | ${duration(s.pos)}/${duration(s.dur)}\n └─ ${s.transcode ? '🔄' : '⏯️'} ${p.quality || s.quality} ${p.bitrate} | ${p.player}\`\`\`**`;
};

// The bot's custom status, as shared/presence.py builds it with the example
// config: libraries while idle, the stream count while someone watches.
const presenceText = () => {
  if (state.server !== 'online') return '🔴 Server Offline!';
  const n = state.streams.length;
  if (n) return `${n} active Stream${n === 1 ? '' : 's'} 🟢`;
  const [movies, tv] = ['Movies', 'TV'].map((name) => LIBRARIES[state.platform].find((lib) => lib.name === name));
  return `${thousands(movies.count)} ${movies.name} ${movies.emoji} | ${thousands(tv.count)} ${tv.name} ${tv.emoji}`;
};

// The member list: the bot with its presence, the watchers without a status
// of their own, all set to Do Not Disturb (they are watching, after all).
const AVATAR_COLORS = ['#c2410c', '#7b5cd6', '#0e7490', '#b45309'];
const membersHTML = () => {
  const people = STREAMS().map((s) => s.user);
  const bot = `<li class="dc-member"><span class="dc-avatar bot"><img src="avatar.svg" alt=""><i class="dc-status${state.server === 'online' ? '' : ' dnd'}"></i></span>`
    + `<span class="dc-member-name"><b>MediaWatch<em class="msg-tag">App</em></b><small>${esc(presenceText())}</small></span></li>`;
  const users = people.map((name, i) => `<li class="dc-member"><span class="dc-avatar" style="background:${AVATAR_COLORS[i % AVATAR_COLORS.length]}">${esc(name[0])}<i class="dc-status dnd"></i></span>`
    + `<span class="dc-member-name"><b>${esc(name)}</b></span></li>`).join('');
  // Grouped by hoisted role, as Discord's member list does.
  return emojify(`<div class="dc-cat">Bots — 1</div><ul>${bot}</ul><div class="dc-cat">Members — ${people.length}</div><ul>${users}</ul>`);
};

const buttonLabel = (i, user) => `Stream ${i} - ${user.length > 15 ? `${user.slice(0, 12)}...` : user}`;

// ---------- embeds ----------

const author = (platform) => ({ name: DASHBOARD_NAME, icon: icon(platform, 24) });

const dashboardEmbed = (platform, server, streams, opts = {}) => {
  const base = { author: author(platform), thumb: logoTile(platform), footer: { text: 'Last updated', icon: icon(platform, 20) }, timestamp: true };
  if (server === 'auth') {
    const key = platform === 'plex' ? 'PLEX_TOKEN' : 'JELLYFIN_API_KEY';
    return { ...base, color: COLOR.orange, title: 'Server rejected the credentials! ⛔', fields: [{
      name: 'Authentication failed:',
      value: `The server is reachable, but it rejected the credentials (HTTP 401/403).\nCheck **${key}** in your \`.env\` file and restart the bot. The media server itself is not down.`,
    }] };
  }
  if (server === 'offline') {
    const since = Math.floor(state.offlineSince / 1000);
    return { ...base, color: COLOR.red, title: 'Server is currently Offline! ⚠️', fields: [
      { name: 'Offline since:', value: `**Since:** <t:${since}:f>\n**Duration:** <t:${since}:R>` },
      { name: 'Uptime (24h)', value: '```98.1% (23h 32m)```', inline: true },
      { name: 'Uptime (7 days)', value: '```99.5% (167h 9m)```', inline: true },
      { name: 'Uptime (30 days)', value: '```99.8% (718h 34m)```', inline: true },
    ] };
  }

  const fields = [];
  if (!opts.only || opts.only === 'libraries') {
    fields.push({ name: 'Server Uptime 🖥️', value: `\`\`\`${uptime(state.uptimeMinutes)}\`\`\``, inline: true }, { name: '', value: '', inline: true }, { name: '', value: '', inline: true });
    let tiles = 0;
    LIBRARIES[platform].forEach((lib) => {
      fields.push({ name: `${lib.name} ${lib.emoji}`, value: `\`\`\`${thousands(lib.count)}\`\`\``, inline: true });
      tiles++;
      if (lib.episodes) {
        fields.push({ name: `${lib.name} Episodes 📺`, value: `\`\`\`${thousands(lib.episodes)}\`\`\``, inline: true });
        tiles++;
      }
    });
    for (let i = tiles % 3 ? 3 - (tiles % 3) : 0; i > 0; i--) fields.push({ name: '\u200b', value: '\u200b', inline: true });
  }
  if (!opts.only || opts.only === 'streams') {
    if (streams.length) {
      const n = streams.length;
      fields.push({ name: `${n} current Stream${n === 1 ? '' : 's'}:`, value: streams.map((s) => streamBlock(s, platform)).join(' ') });
    } else {
      fields.push({ name: 'Current Streams:', value: '💤 *No active streams currently*' });
    }
  }
  // The SABnzbd block only exists while the queue has something in it.
  if (opts.only === 'downloads' || (!opts.only && state.downloads)) {
    fields.push(
      { name: '2 current Downloads:', value: DOWNLOADS.join(' ') },
      { name: 'Downloads 📥', value: '```40.10 GB```', inline: true },
      { name: 'Free Space 💾', value: '```412.50 GB```', inline: true },
      { name: 'Total Space 🗄️', value: '```16.00 TB```', inline: true },
    );
  }
  return { ...base, color: COLOR.green, title: 'Server is currently Online! ✅', fields };
};

const dashboardRows = (platform, server, streams) => {
  const buttons = server === 'online' ? streams.map((s, i) => ({ style: 'primary', emoji: s.emoji, label: buttonLabel(i + 1, s.user), action: `details:${s.id}` })) : [];
  // Plex with global_stats.button_location: both, so the button sits here and
  // under the stream details. It needs Tautulli only, so it stays while the
  // server is idle, offline or rejects the token.
  if (platform === 'plex') buttons.unshift({ style: 'secondary', emoji: '🌐', label: 'Global Stats', action: 'global:0' });
  const rows = [];
  for (let i = 0; i < buttons.length; i += 5) rows.push(buttons.slice(i, i + 5));
  return rows;
};

const detailsEmbed = (s, platform) => {
  const p = s[platform];
  const pad = { name: '\u200b', value: '\u200b', inline: true };
  const title = s.type === 'movie' ? `🎥 ${s.title} (${s.year})` : `📺 ${s.show} - S${pad2(s.season)}E${pad2(s.episode)} - ${s.title}`;
  const now = new Date();
  const status = s.paused ? '`⏸️ Paused`' : '`▶️ Playing`';
  const timing = `\`▶ ${clock24(new Date(now - s.pos * 1000))} | ■ ${clock24(new Date(+now + (s.dur - s.pos) * 1000))}\``;

  const fields = [{ name: '📝 Description', value: s.summary }];
  if (s.type === 'movie') fields.push({ name: '⭐ Rating', value: `\`${s.rating}\``, inline: true }, { name: '🎬 Director', value: `\`${s.director}\``, inline: true }, pad);
  else fields.push({ name: '⭐ Rating', value: `\`${s.rating}\``, inline: true }, { name: '📺 Season', value: `\`Season ${s.season}\``, inline: true }, { name: '✍️ Writer', value: `\`${s.writer}\``, inline: true });
  fields.push(
    { name: '👤 User', value: `\`${s.user}\``, inline: true },
    { name: '📱 Player', value: `\`${p.playerFull}\``, inline: true },
    { name: '📚 Library', value: `\`${s.library}\``, inline: true },
    { name: '📊 Progress', value: `\`${bar(percent(s), false)}\`\n\`${duration(s.pos)} / ${duration(s.dur)}\``, inline: true },
    { name: '⏯️ Status', value: platform === 'plex' ? `${status}\n${timing}` : status, inline: true },
    { name: '🌍 Connection', value: `\`${p.conn}\``, inline: true },
    { name: '📺 Resolution', value: `\`${p.res}\``, inline: true },
    { name: '📊 Bitrate', value: `\`${p.bitrateDetail}\``, inline: true },
    { name: '📁 File', value: `\`${s.file}\``, inline: true },
  );
  if (s.transcode) fields.push({ name: '🔄 Transcoding', value: p.transcoding.join('\n') });
  else {
    fields.push({ name: '⏯️ Playback Mode', value: '`Direct Play`', inline: true }, { name: '🌐 Language', value: `\`${s.lang}\``, inline: true });
    fields.push(p.sub === '\u200b' ? pad : { name: '📝 Subtitle', value: `\`${p.sub}\``, inline: true });
  }
  return {
    color: COLOR[platform], title, fields, author: author(platform), thumb: poster(s),
    url: platform === 'plex' ? 'https://app.plex.tv/desktop' : null,
    footer: { text: s.user, icon: platform === 'plex' ? userIcon(s.user) : icon(platform, 20) }, timestamp: true,
  };
};

const detailsRows = (s, platform) => {
  const kill = { style: 'danger', emoji: '⛔', label: 'Kill Stream', action: `kill:${s.id}` };
  if (platform === 'jellyfin') return [[kill]];
  return [[
    { style: 'secondary', emoji: '🌐', label: 'Global Stats', action: 'global:0' },
    { style: 'primary', emoji: '📊', label: 'User Stats', action: `user:${s.id}:0` },
    { style: 'link', emoji: '▶️', label: 'Plex', url: 'https://app.plex.tv/desktop' },
    kill,
  ]];
};

const unavailable = (platform) => ({
  color: COLOR.red, title: '❌ Stream Details Unavailable', author: author(platform),
  desc: 'This stream is no longer active, or the session cache expired. Please refresh the dashboard and try again.',
  footer: { text: `${platform === 'plex' ? 'Plex' : 'Jellyfin'} Stream Status`, icon: icon(platform, 20) }, timestamp: true,
});

// Plex shows the numeric sessionKey, Jellyfin the session Id (a 32-digit hex GUID).
const sessionId = (s, platform) => (platform === 'plex' ? `${40 + s.id}` : `8f3c2a91d4e64b7f9a0c5e1d27b6f40${s.id}`);

const killedEmbed = (s, platform, reason) => {
  const pad = { name: '\u200b', value: '\u200b', inline: true };
  // Tautulli's year and Jellyfin's ProductionYear belong to the episode, not the show.
  const named = s.type === 'movie' ? `${s.title} (${s.year})` : `${s.show} (${s.episodeYear})`;
  const session = { name: '🔑 Session', value: `\`${sessionId(s, platform)}\``, inline: true };
  const fields = s.type === 'movie'
    ? [{ name: '🎥 Movie', value: `\`${named}\``, inline: true }, session, pad]
    : [{ name: '📺 Series', value: `\`${named}\``, inline: true }, session, pad,
      { name: '📋 Episode', value: `\`S${pad2(s.season)}E${pad2(s.episode)} - ${s.title}\`` }];
  fields.push({ name: '👤 User', value: `\`${s.user.toLowerCase().replace(/[^a-z0-9]/g, '')}\``, inline: true }, { name: '💬 Reason', value: `\`${reason}\``, inline: true }, pad);
  return {
    color: COLOR.red, title: '✅ Stream Killed Successfully', fields, author: author(platform), thumb: logoTile(platform),
    footer: { text: named, icon: icon(platform, 20) }, timestamp: true,
  };
};

// ---------- statistics (Plex with Tautulli) ----------

const periodTiles = (rows) => rows.map(([name, plays, time]) => ({ name, value: `**${plays} plays**\n\`${time}\``, inline: true }));

// Mirrors _generate_peak_hours_chart(): music at the bottom, then movies, then
// TV; title and time range on one line, legend centred under the axis.
const hourlyChart = () => {
  const tv = [3, 2, 1, 1, 0, 0, 0, 1, 1, 2, 2, 3, 4, 4, 5, 6, 8, 11, 15, 19, 26, 20, 14, 7];
  const mv = [2, 1, 1, 0, 0, 0, 0, 0, 1, 1, 1, 2, 2, 2, 3, 3, 4, 6, 9, 13, 20, 15, 9, 4];
  const mu = [0, 0, 0, 0, 0, 0, 1, 2, 3, 2, 2, 2, 3, 2, 2, 2, 2, 1, 1, 1, 2, 1, 0, 0];
  const max = 50;
  const x0 = 36;
  const w = 20;
  const y0 = 212;
  const h = 142;
  let bars = '';
  for (let t = 0; t <= max; t += 10) {
    const y = (y0 - (t / max) * h).toFixed(1);
    bars += `<text x="${x0 - 8}" y="${+y + 3}" fill="#999" font-size="9" text-anchor="end">${t}</text>`;
    if (t) bars += `<line x1="${x0}" x2="${x0 + 24 * w}" y1="${y}" y2="${y}" stroke="#555" stroke-opacity="0.15"/>`;
  }
  tv.forEach((v, i) => {
    let y = y0;
    [[mu[i], '#e85d75'], [mv[i], '#f0f0f0'], [v, '#e5a00d']].forEach(([n, c]) => {
      const bh = (n / max) * h;
      y -= bh;
      if (bh) bars += `<rect x="${x0 + i * w + 1.5}" y="${y.toFixed(1)}" width="${w - 3}" height="${bh.toFixed(1)}" fill="${c}" stroke="#2b2b2b" stroke-width="0.5"/>`;
    });
    bars += `<text x="${x0 + i * w + w / 2}" y="${y0 + 14}" fill="#999" font-size="9" text-anchor="middle">${pad2(i)}</text>`;
  });
  return `<svg viewBox="0 0 540 262" width="100%" role="img" aria-label="Stacked bar chart of plays by hour of day, peaking at 20:00" style="display:block;background:#2b2b2b;font-family:Arial,sans-serif">`
    + `<text x="${x0}" y="30" font-size="14"><tspan fill="#fff">Play count by hour of day</tspan><tspan fill="#999" dx="10">Last 30 days</tspan></text>`
    + `<text x="${x0}" y="50" fill="#999" font-size="11">The combined total of tv, movies, and music played per hour of the day.</text>`
    + `<line x1="${x0}" x2="${x0 + 24 * w}" y1="${y0}" y2="${y0}" stroke="#555" stroke-width="0.5"/>${bars}`
    + `<g font-size="10" fill="#999"><rect x="197" y="236" width="12" height="9" fill="#e5a00d"/><text x="214" y="244">TV</text><rect x="240" y="236" width="12" height="9" fill="#f0f0f0"/><text x="257" y="244">Movies</text><rect x="302" y="236" width="12" height="9" fill="#e85d75"/><text x="319" y="244">Music</text></g></svg>`;
};

// Mirrors _generate_dual_pie_chart(): wedges counter-clockwise from 12 o'clock,
// percentages inside every wedge of 5 % or more, legend under each pie.
const pie = (cx, title, slices) => {
  const total = slices.reduce((sum, [, sec]) => sum + sec, 0);
  let a = -Math.PI / 2;
  const r = 66;
  const cy = 142;
  const pt = (ang, rr) => `${(cx + rr * Math.cos(ang)).toFixed(1)} ${(cy + rr * Math.sin(ang)).toFixed(1)}`;
  const paths = slices.map(([, sec, c]) => {
    const v = sec / total;
    const b = a - v * 2 * Math.PI;
    const d = `M${cx} ${cy} L${pt(a, r)} A${r} ${r} 0 ${v > 0.5 ? 1 : 0} 0 ${pt(b, r)}Z`;
    const [lx, ly] = pt((a + b) / 2, r * 0.6).split(' ');
    a = b;
    const label = v >= 0.05 ? `<text x="${lx}" y="${+ly + 4}" fill="#2b2b2b" font-size="10" font-weight="700" text-anchor="middle">${(v * 100).toFixed(1)}%</text>` : '';
    return `<path d="${d}" fill="${c}" stroke="#2b2b2b" stroke-width="2"/>${label}`;
  }).join('');
  const legend = slices.map(([n, sec, c, time], i) => `<rect x="${cx - 78}" y="${230 + i * 15}" width="11" height="9" fill="${c}"/><text x="${cx - 62}" y="${238 + i * 15}">${n} (${(sec / total * 100).toFixed(1)}% • ${time})</text>`).join('');
  return `<text x="${cx}" y="${cy - r - 14}" fill="#fff" font-size="13" text-anchor="middle">${title}</text>${paths}<g font-size="9" fill="#999">${legend}</g>`;
};
const userCharts = () => `<svg viewBox="0 0 540 290" width="100%" role="img" aria-label="Two pie charts: watch time by device and by content type" style="display:block;background:#2b2b2b;font-family:Arial,sans-serif">`
  + '<text x="30" y="24" font-size="14"><tspan fill="#fff">Watch time distribution by device and content type</tspan><tspan fill="#999" dx="10">All time</tspan></text>'
  + '<text x="30" y="42" fill="#999" font-size="11">Share of total watch time split across playback devices and media types.</text>'
  + pie(140, 'Devices', [['Apple TV', 1855200, '#4a9eff', '21d 11h 20m'], ['Plex Web', 963300, '#9b59b6', '11d 3h 35m'], ['iPhone', 749220, '#2ecc71', '8d 16h 7m']])
  + pie(400, 'Content Types', [['TV Shows', 2440320, '#e5a00d', '28d 5h 52m'], ['Movies', 1127400, '#f0f0f0', '13d 1h 10m']]) + '</svg>';

const pager = (kind, page, pages, extra = '') => [[
  { style: 'secondary', label: '◀ Previous', action: `${kind}:${extra}${page - 1}`, disabled: page === 0 },
  { style: 'primary', label: 'Next ▶', action: `${kind}:${extra}${page + 1}`, disabled: page === pages - 1 },
]];

const globalStats = (page) => {
  const base = { author: author('plex'), thumb: logoTile('plex') };
  if (page === 0) {
    return { ...base, color: COLOR.green, title: '🌐 Global Server Statistics - Overview', footer: { text: 'Page 1/3 • Global Server Statistics', icon: icon('plex', 20) }, timestamp: true, fields: [
      ...periodTiles([['⏱️ Last 24h', 12, '9h 12m'], ['📅 Last 7 days', 64, '2d 7h 40m'], ['📆 Last 30 days', 248, '9d 3h 5m'], ['🌍 All Time', 4912, '187d 6h 51m'], ['📊 Avg per day', 8.3, '7h 18m']]),
      { name: '\u200b', value: '\u200b', inline: true },
      { name: '🎬 Most Popular Movies (Last 30 days)', value: '1. **The Big Lebowski (1998)** - **`14 plays`**\n2. **Ready Player One (2018)** - **`9 plays`**\n3. **Furiosa: A Mad Max Saga (2024)** - **`7 plays`**' },
      { name: '📺 Top TV Shows (Last 30 days)', value: '1. **Mr. Robot (2015)** - **`31 plays`** | **`1d 9h 40m`**\n2. **The Bear (2022)** - **`22 plays`** | **`11h 40m`**\n3. **Shōgun (2024)** - **`17 plays`** | **`16h 12m`**' },
    ] };
  }
  if (page === 1) {
    return { ...base, color: COLOR.blue, title: '🌐 Global Server Statistics - Activity', footer: { text: 'Page 2/3 • Activity Statistics', icon: icon('plex', 20) }, timestamp: true, image: hourlyChart(), fields: [
      { name: '👥 Active Users (Last 30 days)', value: '**`7`** unique users' },
      { name: '⏰ Peak Hour', value: '**`20:00`** with **`48`** plays', inline: true },
      { name: '📅 Most Active Day', value: '**`Saturday`** with **`63`** plays', inline: true },
      { name: '📊 Hourly Activity Chart', value: '' },
    ] };
  }
  const users = [[CREW[1], '2d 3h 45m', 87], [CREW[0], '1d 19h 2m', 71], [CREW[2], '1d 4h 30m', 52], ['Forrest Gump', '22h 10m', 38], ['Ellen Ripley', '14h 5m', 21], ['Indiana Jones', '6h 48m', 12], ['The Dude', '2h 15m', 4]];
  const medal = ['🥇', '🥈', '🥉'];
  return { ...base, color: COLOR.gold, title: '🌐 Top 10 Users by Watch Time (Last 30 days)', footer: { text: 'Page 3/3 • Top Users', icon: icon('plex', 20) }, timestamp: true, fields: [{
    name: '\u200b',
    value: users.map(([n, t, p], i) => `${medal[i] || '🔹'} **${i + 1}.** **${n}**\n\`${t}\` • \`${p} plays\``).join('\n'),
  }] };
};

const userStats = (s, page) => {
  const title = `📊 User Statistics: ${s.user}`;
  const base = { author: author('plex'), thumb: logoTile('plex') };
  if (page === 0) {
    return { ...base, color: COLOR.blue, title, footer: { text: 'Page 1/3 • Watch Behavior', icon: icon('plex', 20) }, timestamp: true, fields: [
      ...periodTiles([['⏱️ Last 24h', 3, '2h 41m'], ['📅 Last 7 days', 14, '11h 20m'], ['📆 Last 30 days', 87, '2d 3h 45m'], ['🌍 All Time', 1204, '41d 7h 2m'], ['📊 Avg per day', 2.9, '1h 43m']]),
      { name: '⏱️ Avg Session', value: '`49m`', inline: true },
      { name: '🔥 Watch Streak', value: '**5 days**', inline: true },
      { name: '\u200b', value: '\u200b', inline: true },
    ] };
  }
  if (page === 1) {
    return { author: base.author, color: COLOR.purple, title, desc: '**Activity & Devices** • All time', image: userCharts(), footer: { text: 'Page 2/3 • Activity & Devices', icon: icon('plex', 20) }, timestamp: true, fields: [
      { name: '⏰ Peak Hour', value: '**`21:00`**\n`34 plays`', inline: true },
      { name: '📅 Most Active Day', value: '**Sunday**\n`41 plays`', inline: true },
      { name: '📱 Most Active Device', value: '**Apple TV**\n`21d 11h 20m`', inline: true },
      { name: '🎬 Top Content Type', value: '**TV Shows**\n`68.4% • 28d 5h 52m`', inline: true },
      { name: '\u200b', value: '\u200b', inline: true },
      { name: '\u200b', value: '\u200b', inline: true },
    ] };
  }
  // One ansi block per podium place, colours as user_stats_pagination.py sets them.
  const top = (fg, t, line) => `\`\`\`ansi\n\x1b[${fg}m${t}\x1b[0m\n\x1b[0;37m   ${line}\x1b[0m\n\`\`\``;
  return { ...base, color: COLOR.gold, title, desc: '**Top TV Shows** • All time', footer: { text: 'Page 3/3 • Top Content', icon: icon('plex', 20) }, timestamp: true, fields: [{
    name: '📺 Most Watched Shows',
    value: `${top('1;33', '🥇 1. Mr. Robot', '31 plays • 1d 9h 40m')}\n${top('1;37', '🥈 2. The Bear', '22 plays • 11h 40m')}\n${top('0;33', '🥉 3. Shōgun', '17 plays • 16h 12m')}\n🏅 **4.** \`Slow Horses\` — **12h 3m** • \`9 plays\`\n🏅 **5.** \`Andor\` — **9h 51m** • \`7 plays\``,
  }] };
};

// ---------- demo state ----------

const $ = (sel, root = document) => root.querySelector(sel);
const list = $('#dc-messages');
const modalLayer = $('#dc-modal');

const state = {};
const messages = new Map();
let nextId = 1;

// Builds the channel from scratch. Switching platform keeps the chosen server
// state and download queue; the first load starts from the defaults.
const reset = (platform = 'plex', keep = false) => {
  const kept = keep ? { server: state.server, downloads: state.downloads, offlineSince: state.offlineSince } : { server: 'online', downloads: false, offlineSince: Date.now() - 7 * 60000 };
  Object.assign(state, { platform, streams: STREAMS(), uptimeMinutes: 4577 }, kept);
  messages.clear();
  list.innerHTML = '';
  post({ dashboard: true, time: clock(new Date(Date.now() - 36 * 60000)) });
  syncControls();
};

const render = (id) => {
  const m = messages.get(id);
  let el = document.getElementById(`m${id}`);
  if (!el) {
    el = document.createElement('li');
    el.id = `m${id}`;
    el.className = `msg new${m.eph ? ' eph' : ''}`;
    list.append(el);
  }
  if (m.dashboard) {
    m.embeds = [dashboardEmbed(state.platform, state.server, state.streams)];
    m.rows = dashboardRows(state.platform, state.server, state.streams);
  }
  el.innerHTML = messageHTML(m);
};

const post = (m) => {
  const id = nextId++;
  messages.set(id, { ...m, id });
  render(id);
  return id;
};

// The channel grows with its messages instead of scrolling inside itself, so
// a new reply is brought into view by scrolling the page: its top lands just
// under the fixed header, even when the reply is taller than the screen.
//
// On phones the client is scaled with CSS zoom, and WebKit's scrollIntoView
// and getBoundingClientRect disagree about zoomed boxes. Layout offsets inside
// the client, times the zoom, plus the unzoomed wrapper's position, do not.
const pageTop = (el) => {
  const dc = el.closest('.dc');
  const zoom = parseFloat(getComputedStyle(dc).zoom) || 1;
  let y = 0;
  for (let n = el; n && n !== dc; n = n.offsetParent) y += n.offsetTop;
  return dc.parentElement.getBoundingClientRect().top + window.scrollY + y * zoom;
};
const reveal = (id) => {
  const el = document.getElementById(`m${id}`);
  const gap = header.offsetHeight + 12;
  const top = pageTop(el);
  const bottom = top + el.offsetHeight * (parseFloat(getComputedStyle(el.closest('.dc')).zoom) || 1);
  // Already fully on screen: leave the page where the reader put it.
  if (top - window.scrollY >= gap && bottom - window.scrollY <= window.innerHeight) return;
  window.scrollTo({ top: top - gap, behavior: matchMedia('(prefers-reduced-motion: reduce)').matches ? 'auto' : 'smooth' });
};

// Dismissing a reply takes the reader back to what they clicked, instead of
// leaving them at the spot where the reply was. The page scrolls up to the
// message above, the reply fades out, then its gap closes, so nothing below
// jumps. Only ever up: a reader who scrolled above it stays where they are.
const dismiss = (li, id) => {
  if (li.dataset.leaving) return;
  li.dataset.leaving = 'true';
  messages.delete(id);
  const reduce = matchMedia('(prefers-reduced-motion: reduce)').matches;
  const prev = li.previousElementSibling;
  if (prev) {
    const zoom = parseFloat(getComputedStyle(prev.closest('.dc')).zoom) || 1;
    const top = pageTop(prev);
    const bottom = top + prev.offsetHeight * zoom;
    const target = Math.max(top - (header.offsetHeight + 12), bottom - window.innerHeight + 24);
    if (target < window.scrollY) window.scrollTo({ top: target, behavior: reduce ? 'auto' : 'smooth' });
  }
  if (reduce || !li.animate) { li.remove(); return; }
  const cs = getComputedStyle(li);
  li.style.overflow = 'hidden';
  li.animate(
    [{ opacity: 1, transform: 'none' }, { opacity: 0, transform: 'translateY(-4px)' }],
    { duration: 160, easing: 'ease-out', fill: 'forwards' },
  ).finished
    .then(() => li.animate(
      [
        { height: `${li.offsetHeight}px`, marginTop: cs.marginTop, paddingTop: cs.paddingTop, paddingBottom: cs.paddingBottom, minHeight: cs.minHeight },
        { height: '0px', marginTop: '0px', paddingTop: '0px', paddingBottom: '0px', minHeight: '0px' },
      ],
      { duration: 220, easing: 'cubic-bezier(0.2, 0, 0, 1)', fill: 'forwards' },
    ).finished)
    .then(() => li.remove());
};

// An interaction answer: a deferred "thinking" reply, then the embed.
const reply = (build, replace) => {
  if (replace) {
    Object.assign(messages.get(replace), build());
    render(replace);
    // A page flip can change the height; keep the page's top in view.
    reveal(replace);
    return;
  }
  const id = post({ eph: true, thinking: true, time: clock(new Date()) });
  reveal(id);
  setTimeout(() => {
    // Dismissed while it was still thinking.
    if (!messages.has(id)) return;
    Object.assign(messages.get(id), { thinking: false }, build());
    render(id);
    reveal(id);
  }, 650);
};

const findStream = (id) => state.streams.find((s) => s.id === +id);
const dashboardId = () => [...messages.values()].find((m) => m.dashboard)?.id;

const refreshDashboard = () => {
  const id = dashboardId();
  if (!id) return;
  render(id);
  $('#dc-members').innerHTML = membersHTML();
};

const actions = {
  details(id) {
    const s = findStream(id);
    reply(() => (s ? { embeds: [detailsEmbed(s, state.platform)], rows: detailsRows(s, state.platform) } : { embeds: [unavailable(state.platform)], rows: [] }));
  },
  kill(id) {
    const s = findStream(id);
    openModal(s);
  },
};

list.addEventListener('click', (event) => {
  const el = event.target.closest('[data-action]');
  if (!el || el.disabled) return;
  const li = el.closest('.msg');
  const msgId = +li.id.slice(1);
  const [name, a, b] = el.dataset.action.split(':');
  if (name === 'dismiss') { dismiss(li, msgId); return; }
  // Stats pagers edit their own message in place, as the bot's views do;
  // the buttons under the stream details open a new reply.
  const inPlace = messages.get(msgId).stats ? msgId : null;
  if (name === 'global') { reply(() => ({ stats: true, embeds: [globalStats(+a)], rows: pager('global', +a, 3) }), inPlace); return; }
  if (name === 'user') {
    const s = STREAMS().find((x) => x.id === +a);
    reply(() => ({ stats: true, embeds: [userStats(s, +b)], rows: pager('user', +b, 3, `${a}:`) }), inPlace);
    return;
  }
  actions[name]?.(a, b, msgId);
});

// ---------- kill stream modal ----------

let lastFocus = null;
const closeModal = () => {
  modalLayer.hidden = true;
  modalLayer.innerHTML = '';
  lastFocus?.focus();
};
const openModal = (s) => {
  lastFocus = document.activeElement;
  modalLayer.innerHTML = `<form class="modal" role="dialog" aria-modal="true" aria-labelledby="modal-title">
    <div class="modal-head">${icon(state.platform, 24)}<h4 id="modal-title">Kill Stream</h4>
      <button class="modal-x" type="button" aria-label="Close"><svg width="24" height="24" aria-hidden="true"><use href="#d-close"/></svg></button></div>
    <div class="modal-body"><label for="kill-reason">Reason Message<span>*</span></label>
      <input id="kill-reason" name="reason" required maxlength="200" placeholder="Stopped by administrator" value="Stopped by administrator"></div>
    <div class="modal-foot"><button type="button" class="btn secondary" data-close>Cancel</button><button type="submit" class="btn primary">Submit</button></div>
  </form>`;
  modalLayer.hidden = false;
  const form = modalLayer.querySelector('form');
  const input = form.querySelector('input');
  input.focus();
  input.select();
  form.querySelector('.modal-x').addEventListener('click', closeModal);
  form.querySelector('[data-close]').addEventListener('click', closeModal);
  form.addEventListener('submit', (event) => {
    event.preventDefault();
    const reason = input.value.trim() || 'Stopped by administrator';
    closeModal();
    const platform = state.platform;
    // The modal opens either way; only the submit finds the stream gone.
    if (!s) { reply(() => ({ text: '❌ This stream is no longer active.', embeds: [], rows: [] })); return; }
    state.streams = state.streams.filter((x) => x !== s);
    reply(() => ({ embeds: [killedEmbed(s, platform, reason)], rows: [] }));
    refreshDashboard();
  });
};
modalLayer.addEventListener('click', (event) => { if (event.target === modalLayer) closeModal(); });
document.addEventListener('keydown', (event) => { if (event.key === 'Escape' && !modalLayer.hidden) closeModal(); });

// ---------- controls ----------

const controls = $('#demo-controls');
const syncControls = () => {
  controls.querySelectorAll('[data-platform]').forEach((b) => b.setAttribute('aria-checked', String(b.dataset.platform === state.platform)));
  controls.querySelectorAll('[data-server]').forEach((b) => b.setAttribute('aria-checked', String(b.dataset.server === state.server)));
  const queue = controls.querySelector('[data-toggle="downloads"]');
  queue.setAttribute('aria-pressed', String(state.downloads));
  // Downloads only show on an online dashboard, as in the bot.
  queue.disabled = state.server !== 'online';
  placeThumbs();
  refreshDashboard();
};
// Slides each group's thumb under its checked option and takes over its tone.
// Measured, because the options are as wide as their labels.
const placeThumbs = () => {
  controls.querySelectorAll('.seg').forEach((seg) => {
    const on = seg.querySelector('[aria-checked="true"]');
    const thumb = seg.querySelector('.seg-thumb');
    if (!on || !thumb) return;
    thumb.style.setProperty('--thumb-x', `${on.offsetLeft}px`);
    thumb.style.setProperty('--thumb-w', `${on.offsetWidth}px`);
    thumb.dataset.tone = on.dataset.tone;
  });
};
// The first placement happens without motion; later ones slide.
const readyThumbs = () => requestAnimationFrame(() => controls.querySelectorAll('.seg').forEach((seg) => seg.classList.add('is-ready')));
window.addEventListener('resize', placeThumbs);
document.fonts?.ready.then(placeThumbs);
controls.hidden = false;
controls.addEventListener('click', (event) => {
  const b = event.target.closest('button');
  if (!b) return;
  if (b.dataset.platform && b.dataset.platform !== state.platform) reset(b.dataset.platform, true);
  else if (b.dataset.toggle === 'downloads') {
    state.downloads = !state.downloads;
    syncControls();
    refreshDashboard();
  } else if (b.dataset.server) {
    state.server = b.dataset.server;
    if (state.server === 'offline') state.offlineSince = Date.now() - 7 * 60000;
    syncControls();
    refreshDashboard();
  }
});

// The dashboard ticks forward, the way the bot's minute edits move it. Skipped
// while focus is inside it so a keyboard user does not lose their place.
setInterval(() => {
  if (state.server !== 'online' || list.querySelector(`#m${dashboardId()}`)?.contains(document.activeElement)) return;
  state.streams.forEach((s) => { if (!s.paused) s.pos = (s.pos + 5) % s.dur; });
  state.uptimeMinutes += 1;
  refreshDashboard();
}, 5000);

reset('plex');
readyThumbs();

// ---------- snippets outside the client ----------

const snippet = (key) => {
  const s = STREAMS();
  const trim = (e) => ({ ...e, footer: null, author: null, thumb: null });
  if (key === 'libraries') return embedHTML(trim(dashboardEmbed('plex', 'online', [], { only: 'libraries' })));
  if (key === 'streams') return embedHTML(trim({ ...dashboardEmbed('plex', 'online', s.slice(1), { only: 'streams' }), title: null }));
  if (key === 'downloads') return embedHTML(trim({ ...dashboardEmbed('plex', 'online', [], { only: 'downloads' }), title: null }));
  if (key === 'offline') return embedHTML(trim(dashboardEmbed('plex', 'offline', [])));
  return embedHTML(detailsEmbed(s[1], 'plex')) + rowsHTML(detailsRows(s[1], 'plex'), false);
};
document.querySelectorAll('[data-snip]').forEach((el) => { el.innerHTML = emojify(snippet(el.dataset.snip)); });

// ---------- hero entrance ----------

const hero = $('.hero');
[...$('.hero-copy').children].forEach((el, i) => el.style.setProperty('--i', i));
requestAnimationFrame(() => hero.classList.add('is-on'));

// ---------- scroll reveal ----------

const items = [...document.querySelectorAll('.reveal')];
document.querySelectorAll('.features, .more-grid, .duo, .steps').forEach((group) => {
  [...group.children].forEach((child, index) => {
    if (child.classList.contains('reveal')) child.style.setProperty('--i', index);
  });
});
const pending = new Set(items);
const show = (el) => { el.classList.add('in'); pending.delete(el); };
if (!window.IntersectionObserver) {
  items.forEach(show);
} else {
  const observer = new IntersectionObserver((entries) => {
    entries.forEach((entry) => {
      if (!entry.isIntersecting) return;
      show(entry.target);
      observer.unobserve(entry.target);
    });
  }, { rootMargin: '0px 0px -10% 0px', threshold: 0.05 });
  items.forEach((el) => observer.observe(el));
  // A very tall window can leave the last block inside the bottom margin at
  // full scroll; a plain on-screen check releases it.
  const sweep = () => {
    pending.forEach((el) => {
      const r = el.getBoundingClientRect();
      if (r.top < window.innerHeight && r.bottom > 0) show(el);
    });
    if (!pending.size) {
      window.removeEventListener('scroll', sweep);
      window.removeEventListener('resize', sweep);
    }
  };
  window.addEventListener('scroll', sweep, { passive: true });
  window.addEventListener('resize', sweep, { passive: true });
}

// ---------- nav ----------

const nav = $('.top-nav');
const glow = nav.querySelector('.nav-glow');
const navLinks = [...nav.querySelectorAll('a')];
const spied = navLinks.map((link) => document.querySelector(link.getAttribute('href'))).filter(Boolean);
let activeLink = null;
let hovered = null;
let scrollLock = false;
let lockTimer;

const light = (link) => {
  navLinks.forEach((other) => other.classList.toggle('lit', other === link));
  if (!link) { glow.style.opacity = '0'; return; }
  glow.classList.toggle('no-slide', glow.style.opacity !== '1');
  glow.style.width = `${link.offsetWidth}px`;
  glow.style.transform = `translateX(${link.offsetLeft}px)`;
  glow.style.opacity = '1';
};
const settle = () => light(hovered || activeLink);

navLinks.forEach((link) => {
  link.addEventListener('pointerenter', (event) => {
    if (event.pointerType !== 'mouse') return;
    hovered = link;
    settle();
  });
  link.addEventListener('click', () => {
    activeLink = link;
    scrollLock = true;
    clearTimeout(lockTimer);
    lockTimer = setTimeout(() => { scrollLock = false; }, 1200);
    settle();
  });
});
nav.addEventListener('pointerleave', () => { hovered = null; settle(); });
window.addEventListener('scroll', () => {
  if (!scrollLock) return;
  clearTimeout(lockTimer);
  lockTimer = setTimeout(() => { scrollLock = false; }, 160);
}, { passive: true });
window.addEventListener('resize', settle);

if (window.IntersectionObserver && spied.length) {
  const visible = new Map();
  const spy = new IntersectionObserver((entries) => {
    entries.forEach((entry) => visible.set(entry.target.id, entry.isIntersecting));
    if (scrollLock) return;
    const current = spied.find((section) => visible.get(section.id));
    activeLink = current ? navLinks.find((link) => link.getAttribute('href') === `#${current.id}`) : null;
    settle();
  }, { rootMargin: '-45% 0px -50% 0px' });
  spied.forEach((section) => spy.observe(section));
}

// ---------- version ----------

// The build prints version.py into the navbar. The newest GitHub release
// replaces it once it is newer, so a release shows before the next page build;
// until 2.0 is published the latest release is still a 1.x, hence the compare.
const siteVersion = document.getElementById('site-version');
const newer = (a, b) => {
  const pa = a.split('.').map(Number);
  const pb = b.split('.').map(Number);
  for (let i = 0; i < 3; i++) if ((pa[i] || 0) !== (pb[i] || 0)) return (pa[i] || 0) > (pb[i] || 0);
  return false;
};
const showVersion = (tag) => {
  const latest = String(tag || '').replace(/^v/, '').trim();
  const built = siteVersion.textContent.replace(/^v/, '');
  if (/^\d+\.\d+\.\d+$/.test(latest) && newer(latest, built)) siteVersion.textContent = `v${latest}`;
};
// Cached per tab: the unauthenticated API allows 60 requests an hour per IP.
const cachedTag = sessionStorage.getItem('mw-latest-release');
if (cachedTag) showVersion(cachedTag);
else {
  fetch('https://api.github.com/repos/nichtlegacy/MediaWatch/releases/latest', { headers: { Accept: 'application/vnd.github+json' } })
    .then((r) => (r.ok ? r.json() : null))
    .then((release) => {
      if (!release?.tag_name) return;
      sessionStorage.setItem('mw-latest-release', release.tag_name);
      showVersion(release.tag_name);
    })
    .catch(() => {});
}

// ---------- copy ----------

document.querySelectorAll('[data-copy-from]').forEach((button) => {
  const use = button.querySelector('use');
  let timer;
  button.addEventListener('click', async () => {
    try {
      await navigator.clipboard.writeText(document.getElementById(button.dataset.copyFrom).textContent);
    } catch {
      return;
    }
    button.classList.add('copied');
    use.setAttribute('href', '#i-check');
    clearTimeout(timer);
    timer = setTimeout(() => {
      button.classList.remove('copied');
      use.setAttribute('href', '#i-copy');
    }, 1600);
  });
});
