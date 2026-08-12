import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';

const source = readFileSync(new URL('../src/components.tsx', import.meta.url), 'utf8');
const appSource = readFileSync(new URL('../src/App.tsx', import.meta.url), 'utf8');
const panelSource = readFileSync(new URL('../src/panel-frame.tsx', import.meta.url), 'utf8');
const constantsSource = readFileSync(new URL('../src/constants.ts', import.meta.url), 'utf8');

assert.match(constantsSource, /export const SPOTIFY_GREEN = "#1db954"/);
assert.match(constantsSource, /export const MAX_VISIBLE_MODEL_CHOICES = 4/);
assert.match(panelSource, /export const PANEL_BACKGROUND = "#48273e"/);
assert.match(panelSource, /export const PANEL_TITLE = "#c8a6ff"/);
assert.match(panelSource, /export const PANEL_PRIMARY = "#fff4f6"/);
assert.match(panelSource, /export const PANEL_SECONDARY = "#808791"/);
assert.match(
    source,
    /import \{ PANEL_BACKGROUND, PANEL_PRIMARY, PANEL_SECONDARY, PanelChoiceList, PanelEmptyRow, PanelFrame, PanelRow, resolvePanelChoiceSegments, type PanelChoiceItem \} from '\.\/panel-frame\.js'/,
);

// The shared formal-panel frame owns the top/title/body/bottom rhythm.
assert.match(
    panelSource,
    /<PanelEmptyRow width=\{boundedWidth\} \/>[\s\S]*color: PANEL_TITLE, bold: true[\s\S]*\{children\}[\s\S]*<PanelEmptyRow width=\{boundedWidth\} \/>/,
);
assert.match(panelSource, /withTrueColorBackground\(value, PANEL_BACKGROUND\)/);
assert.equal((panelSource.match(/<Transform transform=\{withPanelBackground\}>/g) ?? []).length, 2);
assert.match(
    panelSource,
    /color: spotifyTheme \? SPOTIFY_GREEN : BORDER_BLUE,[\s\S]*bold: true/,
);
assert.doesNotMatch(panelSource, /borderStyle=|selectedBackground|backgroundColor=/);
assert.doesNotMatch(panelSource, /selected \? "> "|showSelectionMarker/);

const loginStart = source.indexOf('const LoginChoiceList =');
const slashStart = source.indexOf('const SlashCommandList =');
const helpStart = source.indexOf('const HelpPanel =');
const compactConfirmStart = source.indexOf('const CompactConfirm =');
const languageStart = source.indexOf('const LanguagePanel =');
const compactSetupStart = source.indexOf('const CompactSetup =');
const inputDockStart = source.indexOf('const InputDock =');
const dynamicTailStart = source.indexOf('export const DynamicTail =');

assert.ok(loginStart >= 0);
assert.ok(slashStart > loginStart);
assert.ok(helpStart > slashStart);
assert.ok(compactConfirmStart > helpStart);
assert.ok(languageStart > compactConfirmStart);
assert.ok(compactSetupStart > languageStart);
assert.ok(inputDockStart > compactSetupStart);
assert.ok(dynamicTailStart > inputDockStart);

const loginBody = source.slice(loginStart, slashStart);
const slashBody = source.slice(slashStart, helpStart);
const helpBody = source.slice(helpStart, source.indexOf('const ChatBubble =', helpStart));
const compactConfirmBody = source.slice(compactConfirmStart, languageStart);
const languageBody = source.slice(languageStart, compactSetupStart);
const compactSetupBody = source.slice(compactSetupStart, inputDockStart);
const inputDockBody = source.slice(inputDockStart, dynamicTailStart);
const songCandidateBody = compactConfirmBody.slice(
    compactConfirmBody.indexOf('if (isSongCandidateConfirm)'),
    compactConfirmBody.indexOf('const choiceItems:'),
);

// Login is a formal panel; its text and secret inputs are embedded directly in the frame.
assert.match(loginBody, /<PanelChoiceList/);
assert.match(loginBody, /<PanelFrame width=\{74\} paddingX=\{2\} title=\{authSetup\.title\} hint=\{displayMessage\}>/);
assert.match(
    loginBody,
    /<PromptInput[\s\S]*mask=\{authSetup\.mask \|\| isApiKeyStep \? "\*" : undefined\}[\s\S]*backgroundColor=\{PANEL_BACKGROUND\}[\s\S]*backgroundWidth=\{74\}[\s\S]*backgroundPaddingX=\{2\}/,
);
assert.doesNotMatch(loginBody, /borderStyle=|selectedBackground|selected \? "> "/);

// Slash suggestions are intentionally a pseudo-panel and keep their compact layout.
assert.match(slashBody, /<Box flexDirection="column">/);
assert.match(
    slashBody,
    /const commandColor = selected \? \(spotifyTheme \? SPOTIFY_GREEN : BORDER_BLUE\) : "#fff4f6";/,
);
assert.match(slashBody, /<Text key=\{command\.name\} color=\{commandColor\} bold=\{selected\}/);
assert.doesNotMatch(slashBody, /PanelFrame|PanelChoiceList|backgroundColor=|selected \? "> "/);

// /help is a real panel and therefore uses the shared frame and list.
assert.match(helpBody, /<PanelFrame width=\{width\} title=\{panel\.title\} hint=\{panel\.hint\}>/);
assert.match(helpBody, /<PanelChoiceList[\s\S]*visibleLimit=\{HELP_PANEL_VISIBLE_COMMANDS\}/);
assert.match(helpBody, /color: PANEL_PRIMARY/);
assert.match(helpBody, /color: PANEL_SECONDARY/);
assert.doesNotMatch(helpBody, /borderStyle=|selectedBackground|selected \? "> "/);

// Song candidates keep the special in-place supplement input and one-row gap.
assert.match(compactConfirmBody, /const isSongCandidateConfirm = confirm\.tool_name === "song_candidate"/);
assert.match(songCandidateBody, /<PanelFrame width=\{panelWidth\} title=\{confirm\.message\} hint="press Esc to cancel">/);
assert.match(songCandidateBody, /const isSupplementChoice = Boolean\(choice\.input\)/);
assert.match(songCandidateBody, /\{isSupplementChoice \? \(\s*<PanelEmptyRow width=\{panelWidth\} \/>/);
assert.match(
    songCandidateBody,
    /\{isSupplementChoice && selected \? \([\s\S]*<PromptInput[\s\S]*focus=\{selected && inputFocus\}[\s\S]*placeholder=""[\s\S]*backgroundColor=\{PANEL_BACKGROUND\}[\s\S]*backgroundWidth=\{panelWidth\}[\s\S]*backgroundPaddingX=\{1\}/,
);
assert.match(songCandidateBody, /unselectedBold: isSupplementChoice/);
assert.match(songCandidateBody, /color: isSupplementChoice \? PANEL_SECONDARY : PANEL_PRIMARY/);
assert.match(songCandidateBody, /resolvePanelChoiceSegments\(item, selected, false\)/);
assert.doesNotMatch(songCandidateBody, /borderStyle=|selectedBackground|trailingRowBackgroundMarker|selected \? "> "/);

// Playlist and generic confirms share the same frame while retaining domain formatting.
assert.match(compactConfirmBody, /const isSpotifyConfirm = spotifyTheme \|\| confirm\.tool_name === "spotify_device"/);
assert.match(compactConfirmBody, /choice\.disabled_reason \?\? choice\.description/);
assert.match(compactConfirmBody, /color: choice\.disabled \? PANEL_SECONDARY : PANEL_PRIMARY/);
assert.match(compactConfirmBody, /if \(confirm\.tool_name === "playlist_browse"\)/);
assert.match(compactConfirmBody, /formatPlaylistBrowseName\(choice\.label\)/);
assert.match(compactConfirmBody, /playlistBrowseTrackCount\(choice\)/);
assert.equal((compactConfirmBody.match(/<PanelFrame/g) ?? []).length, 6);
assert.equal((compactConfirmBody.match(/<PanelChoiceList/g) ?? []).length, 5);
assert.match(compactConfirmBody, /confirm\.tool_name === "provider_mode_exit"/);
assert.match(compactConfirmBody, /const includeCancelChoice = confirm\.tool_name === "provider_mode_exit"/);
assert.match(compactConfirmBody, /getVisibleConfirmChoices\(confirm\.choices, includeCancelChoice\)/);
assert.match(compactConfirmBody, /resolveConfirmChoiceDisplayIndex\(confirm\.choices, confirmIndex, includeCancelChoice\)/);
assert.match(
    compactConfirmBody,
    /titleDetailSegments=\{confirm\.warning \? \[[\s\S]*text: "Warning: ", color: "#facc15", bold: true[\s\S]*text: confirm\.warning, color: "#facc15", italic: true/,
);
assert.match(compactConfirmBody, /spotifyTheme=\{isSpotifyConfirm\}/);
assert.doesNotMatch(compactConfirmBody, /borderStyle=|selectedBackgroundColor=|<ChoicePanel|selected \? "> "/);

assert.match(languageBody, /orderedLanguageChoices\(panel\.selected\)/);
assert.match(languageBody, /<PanelFrame width=\{width\} title=\{t\(language, "language\.title"\)\} hint=\{t\(language, "language\.hint"\)\}>/);
assert.match(languageBody, /<PanelChoiceList/);
assert.match(languageBody, /choice === panel\.selected \? `\* \$\{languageLabel\(choice\)\}`/);
assert.doesNotMatch(languageBody, /borderStyle=|<ChoicePanel|selected \? "> "/);

// Setup flows share the visual frame; provider behavior stays local.
assert.match(compactSetupBody, /<PanelFrame[\s\S]*width=\{panelWidth\}[\s\S]*title=\{setupPanel\.title\}/);
assert.match(compactSetupBody, /setupMessageColor\(setupPanel\)/);
assert.match(compactSetupBody, /setupDoneHint\(setupPanel, language\)/);
assert.match(
    compactSetupBody,
    /<PromptInput[\s\S]*placeholder=\{setupPanel\.prompt \?\? inputPlaceholder\}[\s\S]*backgroundColor=\{PANEL_BACKGROUND\}[\s\S]*backgroundWidth=\{panelWidth\}/,
);
assert.doesNotMatch(compactSetupBody, /borderStyle=|selectedBackground|trailingRowBackgroundMarker|\{"> "\}/);

// Model selection is a formal panel, while InputDock itself remains excluded.
assert.match(source, /const formatModelPanelLabel = \(model: AuthMethodChoice\): string => \(\s*model\.label\.padEnd/);
assert.match(inputDockBody, /const insetPanelWidth = Math\.max\(3, Math\.floor\(terminalColumns \?\? 80\) - 2\)/);
assert.match(
    inputDockBody,
    /<PanelFrame width=\{insetPanelWidth\} title=\{modelPanel\.title\} hint=\{modelPanel\.hint\}>[\s\S]*<PanelChoiceList[\s\S]*visibleLimit=\{MAX_VISIBLE_MODEL_CHOICES\}/,
);
assert.match(inputDockBody, /filterModelChoices\(authSetup\?\.models \?\? \[\], input\)/);
assert.match(inputDockBody, /text: "Search: "/);
assert.match(inputDockBody, /const spotifyTheme = Boolean\(spotifyMode\?\.enabled \|\| spotifySetup\)/);
assert.match(inputDockBody, /<SlashCommandList suggestions=\{slashSuggestions\} selectedIndex=\{slashIndex\} spotifyTheme=\{spotifyTheme\} \/>/);
assert.match(inputDockBody, /borderStyle="single" borderColor="#808791"/);
assert.match(inputDockBody, /const spotifyModeBorderLabel = " 🎧 Spotify Mode "/);
assert.match(inputDockBody, /<Text bold color=\{SPOTIFY_GREEN\}>\{spotifyModeBorderLabel\}<\/Text>/);
assert.doesNotMatch(inputDockBody, /`\$\{switchHint\} · > `|: "> "/);

// Existing visibility, focus and submission routing remain unchanged.
assert.match(
    inputDockBody,
    /const showInput = !setupPanel[\s\S]*&& \(!confirm \|\| Boolean\(selectedChoice\?\.input\) && !isSongCandidateConfirm\)/,
);
assert.match(
    inputDockBody,
    /<CompactConfirm[\s\S]*input=\{input\}[\s\S]*inputFocus=\{inputFocus\}[\s\S]*panelWidth=/,
);
assert.match(inputDockBody, /setupPanel \? <CompactSetup/);

assert.match(appSource, /const isModelPanelActive = authSetup\?\.active && authSetup\.step === "model"/);
assert.match(appSource, /const choices = filterModelChoices\(authSetup\?\.models \?\? \[\], input\)/);
assert.match(appSource, /key\.backspace \|\| key\.delete/);
assert.match(appSource, /evt\.active === false && evt\.step === "model"/);
assert.match(appSource, /const selectableConfirmChoices = React\.useMemo\(\(\) => confirm \? getSelectableConfirmChoices\(confirm\.choices, confirm\.tool_name === "provider_mode_exit"\) : \[\], \[confirm\]\)/);
assert.match(appSource, /const decision = resolveConfirmDecisionFromInput\(text, selectableConfirmChoices\)/);
assert.match(appSource, /setConfirmIndex\(\(prev\) => selectableConfirmChoices\.length > 0 \? Math\.min\(selectableConfirmChoices\.length - 1, prev \+ 1\) : 0\)/);
assert.match(appSource, /const isLoginScreenActive = isGenericAuthSetup\(authSetup\) && !isModelPanelActive/);
assert.match(appSource, /completeSlashCommand\(selectedHelpCommand\)/);
assert.match(appSource, /case "spotify_mode":/);
assert.match(appSource, /setSpotifyMode\(\{ enabled: evt\.enabled, device_id: evt\.device_id, device_name: evt\.device_name \}\)/);
