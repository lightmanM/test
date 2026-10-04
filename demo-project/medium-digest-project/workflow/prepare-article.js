const sourceUrl = $json.sourceUrl || $json.url;
const sourceArticle = $('Extract article links').all()
  .map((item) => item.json)
  .find((article) => article.url === sourceUrl);
const content = ($json.content || '').slice(0, 60000);
const system = [
  'You are an editor preparing a Chinese weekly report from Medium articles.',
  'Return only valid JSON. Do not use Markdown fences.',
  'Relevant topics are: llm_agent, vibe_coding, open_source.',
  'Only set relevant=true when the article has substantial value for at least one topic.',
  'Only include GitHub URLs that are explicitly present in the article text; never invent repositories.',
  'Output schema: {relevant:boolean, topics:string[], summary:string, why_relevant:string, github_repositories:[{name:string,url:string}]}',
].join('\n');

return { json: {
  ...$json,
  sourceUrl,
  emailDate: $json.emailDate || sourceArticle?.emailDate || null,
  emailTimestamp: $json.emailTimestamp || sourceArticle?.emailTimestamp || 0,
  model: $('Workflow configuration').first().json.llmModel,
  messages: [
    { role: 'system', content: system },
    { role: 'user', content: JSON.stringify({ title: $json.title || $json.digestTitle, sourceUrl, article: content }) },
  ],
} };
