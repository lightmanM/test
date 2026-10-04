const source = $('Prepare article for LLM').item.json;
const raw = $json.choices?.[0]?.message?.content;
let result = {};
try {
  const cleaned = typeof raw === 'string' ? raw.replace(/^```(?:json)?\s*/i, '').replace(/\s*```$/, '') : '{}';
  result = JSON.parse(cleaned);
} catch (error) {
  result = { relevant: false, topics: [], summary: '', why_relevant: `LLM JSON parse failed: ${error.message}`, github_repositories: [] };
}

return { json: {
  sourceUrl: source.sourceUrl,
  freediumUrl: source.freediumUrl,
  title: source.title || source.digestTitle,
  author: source.author || null,
  emailDate: source.emailDate || null,
  emailTimestamp: source.emailTimestamp || 0,
  contentStatus: 'success',
  relevant: result.relevant === true,
  topics: Array.isArray(result.topics) ? result.topics : [],
  summary: result.summary || '',
  why_relevant: result.why_relevant || '',
  github_repositories: Array.isArray(result.github_repositories) ? result.github_repositories : [],
} };

