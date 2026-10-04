const articles = $input.all().map((item) => item.json)
  .sort((left, right) => {
    const leftTime = Number(left.emailTimestamp) || Date.parse(left.emailDate || '') || 0;
    const rightTime = Number(right.emailTimestamp) || Date.parse(right.emailDate || '') || 0;
    return rightTime - leftTime;
  });
const relevant = articles.filter((article) => article.relevant === true);
const byTopic = new Map();
for (const article of relevant) {
  for (const topic of article.topics || []) {
    if (!byTopic.has(topic)) byTopic.set(topic, []);
    byTopic.get(topic).push(article);
  }
}

const sections = [];
for (const [topic, topicArticles] of byTopic) {
  sections.push(`\n## ${topic}\n${topicArticles.map((article) => {
    const repos = (article.github_repositories || []).map((repo) => `\n  - GitHub: ${repo.name || repo.url} - ${repo.url}`).join('');
    return `### ${article.title}\n${article.summary || 'No summary'}\n\n${article.why_relevant || ''}\n\nSource: ${article.sourceUrl}${repos}`;
  }).join('\n\n')}`);
}

const failed = articles.filter((article) => article.contentStatus === 'failed');
const window = $('Build rolling 7-day window').first().json;
const emailCount = $('Find Medium Daily Digest emails').all().length;
const report = `# Medium Digest report\n\nWindow: ${window.windowLabel}\nGmail messages matched: ${emailCount}\nProcessed ${articles.length} articles; ${relevant.length} matched your topics.${sections.join('') || '\nNo relevant articles found in the 7-day window.'}\n\n_Articles with unavailable full text: ${failed.length}._`;
return [{ json: { report, emailCount, processed: articles.length, relevant: relevant.length, failed: failed.length } }];
