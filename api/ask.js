// api/ask.js — Vercel serverless function
// Holds your Anthropic API key (server-side, never sent to the browser)
// and forwards questions to Claude along with the relevant property data.

export default async function handler(req, res) {
  if (req.method !== "POST") {
    return res.status(405).json({ reply: "Method not allowed." });
  }

  const apiKey = process.env.ANTHROPIC_API_KEY;
  if (!apiKey) {
    return res.status(500).json({ reply: "Server is missing ANTHROPIC_API_KEY. Add it in your Vercel project settings." });
  }

  try {
    const { question, projects } = req.body || {};

    if (!question || typeof question !== "string") {
      return res.status(400).json({ reply: "No question provided." });
    }

    // `projects` is the pre-filtered shortlist your front-end already computed
    // (max ~40 rows). We pass it to Claude as context so answers stay grounded
    // in YOUR data instead of Claude's general knowledge.
    const rows = Array.isArray(projects) ? projects.slice(0, 40) : [];

    // Each row is the raw DATA tuple from your dashboard:
    // [name, lat, lon, tenure, isLanded, developer, minPrice, maxPrice,
    //  totalUnits, soldUnits, minPSF, maxPSF, firstSaleDate]
    const compact = rows.map(d => ({
      name: d[0],
      tenure: d[3] === "fh" ? "Freehold" : d[3] === "lh" ? "Leasehold" : "Unknown",
      type: d[4] ? "Landed" : "High-rise",
      developer: d[5],
      priceMin: d[6],
      priceMax: d[7],
      totalUnits: d[8],
      soldUnits: d[9],
      psfMin: d[10],
      psfMax: d[11],
      firstSale: d[12]
    }));

    const systemPrompt =
      "You are a property market analyst embedded in a map dashboard of new " +
      "property launches in Peninsular Malaysia (2021-2025). Answer the user's " +
      "question using ONLY the project data provided in the user message. Be " +
      "concise and specific: cite project names, prices (in RM), take-up rates " +
      "(sold/total units), and PSF where relevant. If the data doesn't contain " +
      "the answer, say so plainly. Format prices like 'RM 1.2M' or 'RM 450k'. " +
      "Do not invent projects or figures. " +
      "FORMATTING: Reply in plain conversational sentences only. Do NOT use " +
      "Markdown — no '#' headers, no '|' tables, no '---' dividers, no '*' " +
      "bullets, and no '**' bold. When listing several projects, write each on " +
      "its own short line as a simple sentence, e.g. 'The Ophera (KLGCC " +
      "Resort) — high-rise, RM 5.2M–9.7M, 104/150 units sold.' Keep it clean " +
      "and easy to read in a small chat window.";

    const userContent =
      "Question: " + question + "\n\n" +
      "Relevant projects (JSON):\n" + JSON.stringify(compact, null, 0);

    const apiResp = await fetch("https://api.anthropic.com/v1/messages", {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
        "x-api-key": apiKey,
        "anthropic-version": "2023-06-01"
      },
      body: JSON.stringify({
        model: "claude-sonnet-4-6",
        max_tokens: 700,
        system: systemPrompt,
        messages: [{ role: "user", content: userContent }]
      })
    });

    if (!apiResp.ok) {
      const errText = await apiResp.text();
      console.error("Anthropic API error:", apiResp.status, errText);
      return res.status(502).json({ reply: "The AI service returned an error. Please try again." });
    }

    const data = await apiResp.json();
    const reply = (data.content || [])
      .filter(b => b.type === "text")
      .map(b => b.text)
      .join("\n")
      .trim() || "I couldn't generate a response.";

    return res.status(200).json({ reply });
  } catch (err) {
    console.error("Handler error:", err);
    return res.status(500).json({ reply: "Something went wrong on the server." });
  }
}
