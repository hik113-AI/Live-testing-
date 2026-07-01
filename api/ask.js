// api/ask.js — Vercel serverless function (CommonJS — no ESM import/export,
// so this works regardless of package.json "type" settings)
//
// ARCHITECTURE:
// Claude gets a real tool, query_projects, with structured arguments
// (price range, tenure, type, state, keywords, sort). The server runs an
// EXACT, deterministic filter against the FULL dataset (all ~2,800
// projects, loaded from data.json) and hands Claude back real counts and
// real sample rows. Claude never guesses — it always queries first, then
// writes the final answer from what the tool actually returned.

const fs = require("fs");
const path = require("path");
const { STATES, nearestState } = require("./geo.js");

const DATA = JSON.parse(fs.readFileSync(path.join(__dirname, "data.json"), "utf-8"));

// DATA row shape: [name, lat, lon, tenure, isLanded, developer, priceMin,
//                  priceMax, totalUnits, soldUnits, psfMin, psfMax, firstSale]

const TOOLS = [
  {
    name: "query_projects",
    description:
      "Search the property launches database using structured filters. " +
      "ALWAYS call this before answering ANY question about the dataset, " +
      "including meta-questions like 'how many projects do you have' or " +
      "'recommend me something' — call it with empty/omitted filters in " +
      "those cases to get the full totals and a general sample. Never " +
      "answer from memory or guesswork; always query first.",
    input_schema: {
      type: "object",
      properties: {
        priceMin: {
          type: "number",
          description: "Minimum starting price in RM, e.g. 500000 for RM500k. Omit if not specified."
        },
        priceMax: {
          type: "number",
          description: "Maximum starting price in RM, e.g. 1200000 for RM1.2M. Omit if not specified."
        },
        tenure: {
          type: "string",
          enum: ["freehold", "leasehold"],
          description: "Land tenure. Omit if not specified."
        },
        type: {
          type: "string",
          enum: ["landed", "highrise"],
          description: "Property type. Omit if not specified."
        },
        state: {
          type: "string",
          enum: STATES,
          description: "Malaysian state/federal territory to filter by. Omit if not asking about a specific state."
        },
        keywords: {
          type: "array",
          items: { type: "string" },
          description:
            "Words to match against project name or developer name — use this for " +
            "suburb/area names (e.g. 'Bangsar South', 'Mont Kiara'), specific project " +
            "names, or developer names. Omit if not applicable."
        },
        sortBy: {
          type: "string",
          enum: ["cheapest", "dearest", "biggest", "takeup", "newest"],
          description: "How to rank results, e.g. for 'cheapest', 'best-selling', 'biggest' questions. Omit otherwise."
        },
        limit: {
          type: "number",
          description: "How many sample rows to return (default 10, max 40)."
        }
      }
    }
  }
];

const SYSTEM_PROMPT =
  "You are a property market analyst embedded in a map dashboard of new " +
  "property launches in Peninsular Malaysia (2021-2025). " +
  "You have access to a query_projects tool that searches the REAL, " +
  "complete dataset (thousands of projects). ALWAYS call it before " +
  "answering — never guess or answer from memory. " +
  "The tool returns totalInDataset (size of the whole dataset), " +
  "matchedCount (how many projects match your filters, which may be far " +
  "larger than the sample), and a sample of up to `limit` matching rows. " +
  "Use matchedCount directly for any 'how many' question — do not say data " +
  "is unavailable just because the sample list is short. If matchedCount " +
  "is 0, say plainly that nothing matches, and suggest the person broaden " +
  "their filters. " +
  "Cite project names, prices (in RM), take-up rates (sold/total units), " +
  "and PSF where relevant. Format prices like 'RM 1.2M' or 'RM 450k'. Do " +
  "not invent projects or figures — only use what the tool returned. " +
  "FORMATTING: Reply in plain conversational sentences only. Do NOT use " +
  "Markdown — no '#' headers, no '|' tables, no '---' dividers, no '*' " +
  "bullets, no '**' bold. When listing several projects, write each on " +
  "its own short line as a simple sentence, e.g. 'The Ophera (KLGCC " +
  "Resort) — high-rise, RM 5.2M–9.7M, 104/150 units sold.' Keep it clean " +
  "and easy to read in a small chat window.";

function queryProjects(args) {
  const a = args || {};
  let res = DATA;

  if (typeof a.priceMax === "number") res = res.filter(d => d[6] <= a.priceMax);
  if (typeof a.priceMin === "number") res = res.filter(d => d[6] >= a.priceMin);

  if (a.tenure === "freehold") res = res.filter(d => d[3] === "fh");
  else if (a.tenure === "leasehold") res = res.filter(d => d[3] === "lh");

  if (a.type === "landed") res = res.filter(d => d[4] === 1);
  else if (a.type === "highrise") res = res.filter(d => d[4] === 0);

  if (a.state && STATES.includes(a.state)) {
    res = res.filter(d => nearestState(d[1], d[2]) === a.state);
  }

  if (Array.isArray(a.keywords) && a.keywords.length) {
    const kws = a.keywords.map(k => String(k).toLowerCase()).filter(Boolean);
    if (kws.length) {
      res = res.filter(d => {
        const hay = (d[0] + " " + d[5]).toLowerCase();
        return kws.some(k => hay.includes(k));
      });
    }
  }

  const matchedCount = res.length;

  const takeupOf = d => (d[8] ? d[9] / d[8] : 0);
  const parseDate = s => {
    const t = Date.parse(s);
    return isNaN(t) ? -Infinity : t;
  };
  let sorted = res;
  if (a.sortBy === "cheapest") sorted = [...res].sort((x, y) => x[6] - y[6]);
  else if (a.sortBy === "dearest") sorted = [...res].sort((x, y) => y[6] - x[6]);
  else if (a.sortBy === "biggest") sorted = [...res].sort((x, y) => y[8] - x[8]);
  else if (a.sortBy === "takeup") sorted = [...res].sort((x, y) => takeupOf(y) - takeupOf(x));
  else if (a.sortBy === "newest") sorted = [...res].sort((x, y) => parseDate(y[12]) - parseDate(x[12]));

  const limit = Math.min(Math.max(Number(a.limit) || 10, 1), 40);
  const sample = sorted.slice(0, limit).map(d => ({
    name: d[0],
    lat: d[1],
    lon: d[2],
    tenure: d[3] === "fh" ? "Freehold" : d[3] === "lh" ? "Leasehold" : "Unknown",
    type: d[4] ? "Landed" : "High-rise",
    developer: d[5],
    priceMin: d[6],
    priceMax: d[7],
    totalUnits: d[8],
    soldUnits: d[9],
    psfMin: d[10],
    psfMax: d[11],
    firstSale: d[12],
    state: nearestState(d[1], d[2])
  }));

  return { totalInDataset: DATA.length, matchedCount, sample };
}

async function callClaude(apiKey, messages, toolChoice) {
  const body = {
    model: "claude-sonnet-4-6",
    max_tokens: 1024,
    system: SYSTEM_PROMPT,
    tools: TOOLS,
    messages
  };
  if (toolChoice) body.tool_choice = toolChoice;

  const resp = await fetch("https://api.anthropic.com/v1/messages", {
    method: "POST",
    headers: {
      "Content-Type": "application/json",
      "x-api-key": apiKey,
      "anthropic-version": "2023-06-01"
    },
    body: JSON.stringify(body)
  });
  return resp;
}

function extractText(data) {
  return (data.content || [])
    .filter(b => b.type === "text")
    .map(b => b.text)
    .join("\n")
    .trim();
}

module.exports = async function handler(req, res) {
  if (req.method !== "POST") {
    return res.status(405).json({ reply: "Method not allowed." });
  }

  const apiKey = process.env.ANTHROPIC_API_KEY;
  if (!apiKey) {
    return res.status(500).json({ reply: "Server is missing ANTHROPIC_API_KEY. Add it in your Vercel project settings." });
  }

  try {
    const { question, history } = req.body || {};
    if (!question || typeof question !== "string") {
      return res.status(400).json({ reply: "No question provided." });
    }

    const priorTurns = Array.isArray(history) ? history.slice(-6) : [];
    const messages = [
      ...priorTurns
        .filter(m => m && typeof m.content === "string" && (m.role === "user" || m.role === "assistant"))
        .map(m => ({ role: m.role, content: m.content })),
      { role: "user", content: question }
    ];

    // Step 1: force Claude to call query_projects — it can't skip straight
    // to an unsupported answer.
    let apiResp = await callClaude(apiKey, messages, { type: "tool", name: "query_projects" });
    if (!apiResp.ok) {
      const errText = await apiResp.text();
      console.error("Anthropic API error (step 1):", apiResp.status, errText);
      return res.status(502).json({ reply: "The AI service returned an error. Please try again." });
    }
    let data = await apiResp.json();

    let lastSample = [];
    let loopCount = 0;

    while (data.stop_reason === "tool_use" && loopCount < 3) {
      loopCount++;
      messages.push({ role: "assistant", content: data.content });

      const toolUseBlocks = data.content.filter(b => b.type === "tool_use");
      const toolResults = [];
      for (const block of toolUseBlocks) {
        if (block.name === "query_projects") {
          const result = queryProjects(block.input);
          lastSample = result.sample;
          toolResults.push({
            type: "tool_result",
            tool_use_id: block.id,
            content: JSON.stringify(result)
          });
        } else {
          toolResults.push({
            type: "tool_result",
            tool_use_id: block.id,
            content: "Unknown tool.",
            is_error: true
          });
        }
      }
      messages.push({ role: "user", content: toolResults });

      apiResp = await callClaude(apiKey, messages, undefined);
      if (!apiResp.ok) {
        const errText = await apiResp.text();
        console.error("Anthropic API error (loop):", apiResp.status, errText);
        return res.status(502).json({ reply: "The AI service returned an error. Please try again." });
      }
      data = await apiResp.json();
    }

    const reply = extractText(data) || "I couldn't generate a response.";
    return res.status(200).json({ reply, results: lastSample });
  } catch (err) {
    console.error("Handler error:", err);
    return res.status(500).json({ reply: "Something went wrong on the server." });
  }
};

module.exports.queryProjects = queryProjects;
