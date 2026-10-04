const now = new Date();
const receivedAfterDate = new Date(now.getTime() - 7 * 24 * 60 * 60 * 1000);
const iso = (value) => value.toISOString();

return [{
  json: {
    receivedAfter: iso(receivedAfterDate),
    receivedBefore: iso(now),
    windowLabel: `${iso(receivedAfterDate).slice(0, 16)} to ${iso(now).slice(0, 16)} UTC`,
    gmailSearch: 'Medium',
  },
}];

