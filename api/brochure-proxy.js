/**
 * Proxies TEDUH brochure PDFs from hims.kpkt.gov.my.
 * ?mode=img  — extracts the largest embedded JPEG and returns it as image/jpeg (30-day CDN cache)
 * (default)  — returns the raw PDF with CORS headers (7-day CDN cache)
 */
export const config = { maxDuration: 20 };

function extractLargestJpeg(buf) {
  const jpegs = [];
  let i = 0;
  while (i < buf.length - 3) {
    if (buf[i] === 0xFF && buf[i + 1] === 0xD8 && buf[i + 2] === 0xFF) {
      let j = i + 2;
      while (j < buf.length - 1) {
        if (buf[j] === 0xFF && buf[j + 1] === 0xD9) {
          jpegs.push(buf.slice(i, j + 2));
          i = j + 2;
          break;
        }
        j++;
      }
      if (j >= buf.length - 1) break;
    } else {
      i++;
    }
  }
  if (!jpegs.length) return null;
  return jpegs.reduce((a, b) => a.length > b.length ? a : b);
}

export default async function handler(req, res) {
  const { url, mode } = req.query;

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

    const buffer = Buffer.from(await upstream.arrayBuffer());

    if (mode === 'img') {
      const jpeg = extractLargestJpeg(buffer);
      if (!jpeg) return res.status(404).end();
      res.setHeader('Content-Type', 'image/jpeg');
      res.setHeader('Access-Control-Allow-Origin', '*');
      res.setHeader('Cache-Control', 'public, s-maxage=2592000, stale-while-revalidate=86400');
      return res.end(jpeg);
    }

    res.setHeader('Content-Type', 'application/pdf');
    res.setHeader('Access-Control-Allow-Origin', '*');
    res.setHeader('Cache-Control', 'public, s-maxage=604800, stale-while-revalidate=86400');
    res.end(buffer);
  } catch {
    res.status(502).end();
  }
}
