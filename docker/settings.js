// Minimal Node-RED settings for the J1939 simulator container
module.exports = {
    flowFile: 'flows.json',
    credentialSecret: false,           // flow has no credentials
    uiPort: process.env.PORT || 1880,
    uiHost: process.env.UI_HOST || '0.0.0.0',
    // 'file' store => engine hours survive restarts (saved in /data/context)
    contextStorage: {
        default: { module: 'memory' },
        file: { module: 'localfilesystem', config: { flushInterval: 10 } }
    },
    diagnostics: { enabled: false },
    runtimeState: { enabled: false },
    logging: { console: { level: 'info', metrics: false, audit: false } },
    editorTheme: { projects: { enabled: false }, tours: false },
    exportGlobalContextKeys: false,
    externalModules: { palette: { allowInstall: true } }
};
