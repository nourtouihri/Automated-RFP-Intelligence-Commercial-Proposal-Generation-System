// @ts-check
// Design features the backend does not support yet. Each renders with a "Future"
// label and does nothing. When the backend ships one, delete its key here and
// remove every `FUTURE.<key>` branch (grep for it) in favour of the real feature.
window.UIP = window.UIP || {};

window.UIP.FUTURE = {
  sectionEdit: 'Editing a section needs an edit endpoint.',
  sectionHistory: 'Version history needs stored revisions.',
  promptEdit: 'Prompt-editing a section needs a refine endpoint; it is in progress.',
  conflictResolve: 'Choosing a value needs a conflict-resolution endpoint.',
  share: 'Sharing needs user accounts.',
  pushNotifications: 'Email or push alerts need an event feed; alerts here are derived from service responses.',
  serverSettings: 'Server-side settings (tokens, models, service addresses) need a configuration endpoint.',
  sso: 'Single sign-on needs user accounts and an identity provider.',
  collaboration: 'Working on one deck together without version chaos needs user accounts and stored revisions.',
  salesforce: 'Pushing tenders and decks to Salesforce needs a connector service.',
  googleDrive: 'Saving decks to Google Drive needs a connector service.',
};
