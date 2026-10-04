const sourceUrl = $json.sourceUrl || $json.url;
const sourceArticle = $('Extract article links').all()
  .map((item) => item.json)
  .find((article) => article.url === sourceUrl);

return { json: {
  sourceUrl,
  freediumUrl: $json.freediumUrl || null,
  title: $json.title || sourceArticle?.digestTitle || 'Untitled article',
  author: null,
  emailDate: $json.emailDate || sourceArticle?.emailDate || null,
  emailTimestamp: $json.emailTimestamp || sourceArticle?.emailTimestamp || 0,
  contentStatus: 'failed',
  relevant: false,
  topics: [],
  summary: '',
  why_relevant: `Full text unavailable: ${$json.error || 'unknown error'}`,
  github_repositories: [],
} };

