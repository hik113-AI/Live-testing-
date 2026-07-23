/**
 * Proxies TEDUH brochure PDFs from hims.kpkt.gov.my with CORS headers,
 * enabling PDF.js to render them in the browser.
 * Cached at the Vercel CDN edge for 7 days per URL.
 */
export const config = { maxDuration: 15 };

export default async function handler(req, res) {
  const { url } = req.query;

  if (!url || !url.startsWith('https://hims.kpkt.gov.my/')) {
    return res.status(400).json({ error: 'Invalid URL' });
  }

  try {
    const upstream = await fetch(url, {
      headers: {
        'User-Agent': 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) Chrome/120',
        'Referer': 'https://teduh.kpkt.gov.my/',
      },
    });
    if (!upstream.ok) return res.status(upstream.status).end();

    const buffer = await upstream.arrayBuffer();
    res.setHeader('Content-Type', 'application/pdf');
    res.setHeader('Access-Control-Allow-Origin', '*');
    res.setHeader('Cache-Control', 'public, s-maxage=604800, stale-while-revalidate=86400');
    res.end(Buffer.from(buffer));
  } catch {
    res.status(502).end();
  }
}
