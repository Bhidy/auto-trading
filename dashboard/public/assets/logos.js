/**
 * Logo resolver for the Auto Trading dashboard.
 *
 * Priority:
 *   1. Local PNG  → /assets/logos/{SYMBOL}.png  (committed to repo, 128×128)
 *   2. logo.dev CDN fallback (requires publishable key, for any new symbols)
 *   3. Inline SVG text-initial placeholder (always works, zero network)
 *
 * Sources:
 *   - logo.dev (pk_XldCCgGITcKAcfCcVh8lXg): stocks with real brand logos
 *     AAPL AMD AMZN GOOGL INTC META MS MSFT NFLX NVDA QQQ TSLA
 *   - Custom Pillow-rendered PNGs (sector-colour gradient + ticker text):
 *     All ETFs (SPY DIA BIL GLD IWM SHY TLT + all XL* sector ETFs) and JPM
 *
 * Usage:
 *   import { getLogoUrl, renderLogoImg, logoImgHtml } from '/assets/logos.js';
 *
 *   const src = getLogoUrl('AAPL');          // '/assets/logos/AAPL.png'
 *   const img = renderLogoImg('XLK', { size: 32, className: 'sym-logo' });
 *   container.appendChild(img);
 */

const LOGO_DEV_TOKEN = 'pk_XldCCgGITcKAcfCcVh8lXg';

/**
 * All 31 symbols with local PNGs in /assets/logos/.
 * DO NOT re-download the ETF/JPM ones from logo.dev — they return generic
 * fund-manager logos (State Street, iShares, Invesco) which are not
 * symbol-specific. The custom-rendered versions are intentional.
 */
const LOCAL_SYMBOLS = new Set([
  'AAPL','AMD','AMZN','BIL','BTC_USD','DIA','ETH_USD','GLD','GOOGL','INTC','IWM','META','MSFT','NFLX','NVDA','QQQ','SHY','SPY','TLT','TSLA',
  'XLB','XLC','XLE','XLF','XLI','XLK','XLP','XLRE','XLU','XLV','XLY'
]);

/**
 * Returns the best available logo URL for a ticker symbol.
 * @param {string} symbol  - Ticker (e.g. 'AAPL', 'NVDA')
 * @param {number} [size=64] - Pixel size for CDN fallback
 * @returns {string}
 */
export function getLogoUrl(symbol, size = 64) {
  let sym = (symbol || '').toUpperCase().trim();
  if (sym.includes('BTC') || sym === 'BTC/USD' || sym === 'BTCUSD' || sym === 'BTC-USD' || sym === 'BTC_USD') {
    sym = 'BTC_USD';
  } else if (sym.includes('ETH') || sym === 'ETH/USD' || sym === 'ETHUSD' || sym === 'ETH-USD' || sym === 'ETH_USD') {
    sym = 'ETH_USD';
  } else {
    sym = sym.replace('/', '-');
  }

  if (LOCAL_SYMBOLS.has(sym)) {
    return `/assets/logos/${sym}.svg`;
  }
  // CDN fallback for any symbol not pre-downloaded
  return `https://img.logo.dev/ticker/${sym}?token=${LOGO_DEV_TOKEN}&size=${size}&format=png`;
}

/**
 * Creates an <img> element with a graceful 2-step fallback:
 *   local SVG -> CDN -> SVG placeholder
 *
 * @param {string} symbol
 * @param {{ size?: number, className?: string, alt?: string }} [opts]
 * @returns {HTMLImageElement}
 */
export function renderLogoImg(symbol, opts = {}) {
  const { size = 32, className = '', alt } = opts;
  let sym = (symbol || '').toUpperCase().trim();
  if (sym.includes('BTC') || sym === 'BTC/USD' || sym === 'BTCUSD' || sym === 'BTC-USD' || sym === 'BTC_USD') {
    sym = 'BTC_USD';
  } else if (sym.includes('ETH') || sym === 'ETH/USD' || sym === 'ETHUSD' || sym === 'ETH-USD' || sym === 'ETH_USD') {
    sym = 'ETH_USD';
  } else {
    sym = sym.replace('/', '-');
  }

  const img = document.createElement('img');
  img.width  = size;
  img.height = size;
  img.alt    = alt ?? sym;
  img.style.borderRadius = '50%';
  img.style.objectFit   = 'contain';
  if (className) img.className = className;

  // Track fallback state
  let step = 0;
  const sources = [
    `/assets/logos/${sym}.svg`,
    `https://img.logo.dev/ticker/${sym.replace('_', '-')}?token=${LOGO_DEV_TOKEN}&size=${size}&format=png`,
  ];

  img.src = sources[0];
  img.onerror = () => {
    step++;
    if (step < sources.length) {
      img.src = sources[step];
    } else {
      // Final fallback: inline SVG with first letter
      img.onerror = null;
      const letter = sym.charAt(0) || '?';
      const svg = `<svg xmlns="http://www.w3.org/2000/svg" width="${size}" height="${size}" viewBox="0 0 ${size} ${size}">
        <circle cx="${size/2}" cy="${size/2}" r="${size/2}" fill="#E55A1F"/>
        <text x="50%" y="54%" dominant-baseline="middle" text-anchor="middle"
              font-family="Manrope,sans-serif" font-weight="700"
              font-size="${Math.round(size * 0.42)}" fill="#fff">${letter}</text>
      </svg>`;
      img.src = 'data:image/svg+xml;base64,' + btoa(svg);
    }
  };
  return img;
}

/**
 * Convenience: returns an inline <img> HTML string (non-reactive, no fallback chain).
 * Safe for server-side templates or innerHTML.
 * @param {string} symbol
 * @param {number} [size=32]
 * @param {string} [cls='']
 * @returns {string}
 */
export function logoImgHtml(symbol, size = 32, cls = '') {
  let sym = (symbol || '').toUpperCase().trim();
  if (sym.includes('BTC') || sym === 'BTC/USD' || sym === 'BTCUSD' || sym === 'BTC-USD' || sym === 'BTC_USD') {
    sym = 'BTC_USD';
  } else if (sym.includes('ETH') || sym === 'ETH/USD' || sym === 'ETHUSD' || sym === 'ETH-USD' || sym === 'ETH_USD') {
    sym = 'ETH_USD';
  } else {
    sym = sym.replace('/', '-');
  }

  const src = getLogoUrl(sym, size);
  return `<img src="${src}" width="${size}" height="${size}" alt="${sym}" ` +
         `class="${cls}" style="border-radius:50%;object-fit:contain;" ` +
         `onerror="this.onerror=null;this.src='https://img.logo.dev/ticker/${sym.replace('_', '-')}?token=${LOGO_DEV_TOKEN}&size=${size}&format=png'">`;
}
