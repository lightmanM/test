const window = $('Build rolling 7-day window').first().json;
const emailCount = $('Find Medium Daily Digest emails').all().length;
return [{ json: {
  report: `# Medium Digest report\n\nWindow: ${window.windowLabel}\nGmail messages matched: ${emailCount}\nNo Medium article links were found in the 7-day email window.`,
  emailCount,
} }];
