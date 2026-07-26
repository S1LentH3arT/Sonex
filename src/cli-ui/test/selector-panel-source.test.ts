import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';

const source = readFileSync(new URL('../src/components.tsx', import.meta.url), 'utf8');
const appSource = readFileSync(new URL('../src/App.tsx', import.meta.url), 'utf8');
const constantsSource = readFileSync(new URL('../src/constants.ts', import.meta.url), 'utf8');

assert.match(source, /type ChoicePanelRow =/);
assert.match(
    source,
    /const ChoicePanel = \(\{ rows, selectedIndex, visibleLimit, selectedBackgroundColor, showSelectionMarker = true, boldSelected = false, marginTop = 1 \}/,
);
assert.match(
    source,
    /<Box flexDirection="column" marginTop=\{marginTop\}>/,
);
assert.match(
    source,
    /<Text key=\{row\.key\} backgroundColor=\{rowBackgroundColor\} bold=\{boldSelected && selected\}>/,
);
assert.match(
    source,
    /\{showSelectionMarker \? \([\s\S]*\{selected \? "> " : "  "\}[\s\S]*\) : null\}/,
);
assert.match(constantsSource, /export const SPOTIFY_GREEN = "#1db954"/);
assert.match(source, /import \{[\s\S]*SPOTIFY_GREEN[\s\S]*\} from '\.\/constants\.js'/);
assert.match(source, /const CONFIRM_CHOICE_LABEL_WIDTH = 18/);
assert.match(source, /const CONFIRM_CHOICE_ROW_LABEL_WIDTH = 102/);
assert.match(source, /const PLAYLIST_BROWSE_NAME_WIDTH = 32/);
assert.match(source, /const formatChoicePanelLabel = \(row: ChoicePanelRow\): string =>/);
assert.match(source, /stringWidth\(row\.label\)/);
assert.match(source, /formatMusicCandidateDisplayLabel\(row\.display, CONFIRM_CHOICE_ROW_LABEL_WIDTH, row\.description\)/);
assert.match(source, /row\.label \+ " "\.repeat\(Math\.max\(0, row\.labelWidth - stringWidth\(row\.label\)\)\)/);
assert.match(source, /<Text color=\{rowColor\} backgroundColor=\{rowBackgroundColor\} wrap="truncate-end">\{formatChoicePanelLabel\(row\)\}<\/Text>/);
assert.match(source, /row\.description && row\.display\?\.kind !== "music_candidate"/);
assert.match(source, /selectedBackgroundColor/);
assert.match(source, /backgroundColor=\{rowBackgroundColor\}/);
assert.doesNotMatch(source, /<Text color=\{rowColor\}> - <\/Text>/);
assert.match(source, /<Text color=\{rowColor\} backgroundColor=\{rowBackgroundColor\}>\{row\.description\}<\/Text>/);
assert.match(source, /const SPOTIFY_SELECTED_TEXT = "#06140c"/);
assert.match(source, /const MODEL_PANEL_LABEL_WIDTH = 20/);
assert.match(source, /modelIdFromChoice\(model\)\.padEnd\(MODEL_PANEL_LABEL_WIDTH, " "\)/);

const compactConfirmStart = source.indexOf('const CompactConfirm =');
const languagePanelStart = source.indexOf('const LanguagePanel =');
const compactSetupStart = source.indexOf('const CompactSetup =');
const inputDockStart = source.indexOf('const InputDock =');
const slashCommandListStart = source.indexOf('const SlashCommandList =');
const helpPanelStart = source.indexOf('const HelpPanel =');
assert.ok(compactConfirmStart >= 0);
assert.ok(languagePanelStart > compactConfirmStart);
assert.ok(compactSetupStart > languagePanelStart);
assert.ok(inputDockStart > languagePanelStart);
assert.ok(slashCommandListStart >= 0);
assert.ok(helpPanelStart > slashCommandListStart);

const compactConfirmBody = source.slice(compactConfirmStart, languagePanelStart);
const languagePanelBody = source.slice(languagePanelStart, inputDockStart);
const compactSetupBody = source.slice(compactSetupStart, inputDockStart);
const inputDockBody = source.slice(inputDockStart, source.indexOf('export const DynamicTail =', inputDockStart));
const slashCommandListBody = source.slice(slashCommandListStart, helpPanelStart);
const songCandidateBranch = compactConfirmBody.slice(
    compactConfirmBody.indexOf('if (isSongCandidateConfirm)'),
    compactConfirmBody.indexOf('if (confirm.tool_name === "playlist_browse")'),
);

assert.match(
    slashCommandListBody,
    /const commandColor = selected \? \(spotifyTheme \? SPOTIFY_GREEN : BORDER_BLUE\) : "#fff4f6";/,
);
assert.match(
    slashCommandListBody,
    /<Text key=\{command\.name\} color=\{commandColor\} bold=\{selected\} wrap="truncate-end">/,
);
assert.match(slashCommandListBody, /\{formatCommandListLabel\(command\)\}/);
assert.match(
    slashCommandListBody,
    /const descriptionColor = selected \? commandColor : "#808791";/,
);
assert.match(
    slashCommandListBody,
    /<Text color=\{descriptionColor\}>\{command\.description\}<\/Text>/,
);
assert.doesNotMatch(slashCommandListBody, /color="#9d7787">\{command\.description\}/);
assert.doesNotMatch(slashCommandListBody, /rowBackgroundColor/);
assert.doesNotMatch(slashCommandListBody, /rowFill/);
assert.doesNotMatch(slashCommandListBody, /backgroundColor=/);
assert.doesNotMatch(slashCommandListBody, /selected \? "> " : "  "/);
assert.doesNotMatch(slashCommandListBody, /SPOTIFY_SELECTED_TEXT/);
assert.match(slashCommandListBody, /<Box flexDirection="column">/);
assert.doesNotMatch(slashCommandListBody, /paddingX=/);
assert.match(
    inputDockBody,
    /<Box flexDirection="column" flexShrink=\{0\} paddingX=\{1\}>[\s\S]*<SlashCommandList/,
);
assert.match(
    inputDockBody,
    /borderStyle="single" borderColor="#808791"[\s\S]*paddingX=\{1\} paddingTop=\{0\}/,
);

assert.match(compactConfirmBody, /<ChoicePanel/);
assert.match(compactConfirmBody, /const visibleChoices = getVisibleConfirmChoices\(confirm\.choices\);/);
assert.match(compactConfirmBody, /spotifyTheme = false/);
assert.match(compactConfirmBody, /const isSpotifyConfirm = spotifyTheme \|\| confirm\.tool_name === "spotify_device"/);
assert.match(
    source,
    /import \{ CHAT_SYSTEM_MARKER_COLOR,[\s\S]*\} from '\.\/chat-message\.js'/,
);
assert.match(
    compactConfirmBody,
    /const isSongCandidateConfirm = confirm\.tool_name === "song_candidate";/,
);
assert.match(
    songCandidateBranch,
    /if \(isSongCandidateConfirm\) \{[\s\S]*<Box flexDirection="column" paddingLeft=\{1\} paddingRight=\{0\} borderStyle="round" borderColor="#808791">/,
);
assert.match(
    songCandidateBranch,
    /<Text bold color=\{CHAT_SYSTEM_MARKER_COLOR\}>Select the version to play<\/Text>/,
);
assert.match(
    songCandidateBranch,
    /<Text color="#7f5d6b">press Esc to cancel<\/Text>/,
);
assert.match(
    songCandidateBranch,
    /press Esc to cancel<\/Text>\s*<Box height=\{1\} \/>\s*<ChoicePanel/,
);
assert.match(
    songCandidateBranch,
    /<ChoicePanel[\s\S]*showSelectionMarker=\{false\}[\s\S]*boldSelected=\{true\}[\s\S]*marginTop=\{0\}[\s\S]*\/>\s*<\/Box>/,
);
assert.doesNotMatch(songCandidateBranch, /selectedBackgroundColor=/);
assert.doesNotMatch(songCandidateBranch, /confirmCancelHint/);
assert.doesNotMatch(songCandidateBranch, /backgroundColor=|SONG_CANDIDATE_PANEL_BACKGROUND|rowWidth=|rowPaddingX=/);
assert.doesNotMatch(songCandidateBranch, /paddingBottom=\{1\}|paddingY=\{1\}/);
assert.doesNotMatch(songCandidateBranch, /borderTop=\{true\}/);
assert.doesNotMatch(songCandidateBranch, /border(?:Top|Bottom|Left|Right)=\{false\}/);
assert.match(compactConfirmBody, /if \(confirm\.tool_name === "playlist_browse"\) \{/);
assert.match(compactConfirmBody, /<PlaylistBrowsePanel choices=\{visibleChoices\} selectedIndex=\{confirmIndex\} spotifyTheme=\{isSpotifyConfirm\} \/>/);
assert.match(compactConfirmBody, /borderColor=\{isSpotifyConfirm \? SPOTIFY_GREEN : BORDER_BLUE\}/);
assert.match(compactConfirmBody, /<Text color="#7f5d6b">\{confirmCancelHint\(confirm\.choices\)\}<\/Text>/);
assert.match(compactConfirmBody, /labelWidth: CONFIRM_CHOICE_LABEL_WIDTH,/);
assert.match(compactConfirmBody, /display: choice\.display,/);
assert.match(compactConfirmBody, /selectedBackgroundColor=\{isSpotifyConfirm \? SPOTIFY_GREEN : undefined\}/);
assert.match(source, /const PlaylistBrowsePanel = \(\{ choices, selectedIndex, spotifyTheme = false \}/);
assert.match(source, /formatPlaylistBrowseName\(choice\.label\)/);
assert.match(source, /PLAYLIST_BROWSE_NAME_WIDTH/);
assert.match(source, /playlistBrowseTrackCount\(choice\)/);
assert.doesNotMatch(source, /tool_name: "playlist_browse"[\s\S]*labelWidth: CONFIRM_CHOICE_LABEL_WIDTH/);
assert.match(languagePanelBody, /<ChoicePanel/);
assert.match(languagePanelBody, /orderedLanguageChoices\(panel\.selected\)/);
assert.match(languagePanelBody, /label: choice === panel\.selected \? `\* \$\{languageLabel\(choice\)\}` : languageLabel\(choice\)/);
assert.doesNotMatch(languagePanelBody, /description: choice === panel\.selected \? "current" : choice/);
assert.match(compactSetupBody, /spotifyTheme = false/);
assert.match(compactSetupBody, /borderColor=\{spotifyTheme \? SPOTIFY_GREEN : BORDER_BLUE\}/);
assert.match(compactSetupBody, /<Text color=\{spotifyTheme \? SPOTIFY_GREEN : "#fff4f6"\}>\{setupPanel\.title\}<\/Text>/);
assert.match(compactSetupBody, /<Text color=\{spotifyTheme \? SPOTIFY_GREEN : "#7f5d6b"\}>\{"> "\}<\/Text>/);
assert.match(inputDockBody, /modelPanel/);
assert.match(inputDockBody, /formatModelPanelLabel\(model\)/);
assert.match(inputDockBody, /<ChoicePanel[\s\S]*rows=\{modelPanel\.rows\}/);
assert.match(inputDockBody, /const setupPanel = spotifySetup \?\? \(authSetup && authSetup\.step !== "model" \? authSetup : null\);/);
assert.match(inputDockBody, /const spotifyTheme = Boolean\(spotifyMode\?\.enabled \|\| spotifySetup\);/);
assert.match(inputDockBody, /<SlashCommandList suggestions=\{slashSuggestions\} selectedIndex=\{slashIndex\} spotifyTheme=\{spotifyTheme\} \/>/);
assert.match(inputDockBody, /const showInput = !setupPanel && !helpPanel && !languagePanel && !modelPanel && \(!confirm \|\| Boolean\(selectedChoice\?\.input\)\);/);
assert.match(inputDockBody, /<CompactConfirm confirm=\{confirm\} confirmIndex=\{confirmIndex\} spotifyTheme=\{spotifyTheme\} \/>/);
assert.match(inputDockBody, /spotifyTheme=\{Boolean\(spotifySetup\)\}/);
assert.match(inputDockBody, /const spotifyModeBorderLabel = " 🎧 Spotify Mode ";/);
assert.match(inputDockBody, /borderTop=\{true\}/);
assert.match(inputDockBody, /borderBottom=\{true\}/);
assert.match(inputDockBody, /borderLeft=\{false\}/);
assert.match(inputDockBody, /borderRight=\{false\}/);
assert.match(inputDockBody, /borderStyle="single" borderColor="#808791"/);
assert.match(inputDockBody, /<Text color="#7f5d6b">/);
assert.doesNotMatch(inputDockBody, /borderColor=\{spotifyMode\?\.enabled \? SPOTIFY_GREEN/);
assert.doesNotMatch(inputDockBody, /<Text color=\{spotifyMode\?\.enabled \? SPOTIFY_GREEN/);
assert.match(inputDockBody, /\{minimal && switchHint \? `\$\{switchHint\} · ` : ""\}/);
assert.doesNotMatch(inputDockBody, /`\$\{switchHint\} · > `/);
assert.doesNotMatch(inputDockBody, /: "> "/);
assert.doesNotMatch(inputDockBody, /paddingBottom=\{1\}/);
assert.match(inputDockBody, /minHeight=\{3\}/);
assert.doesNotMatch(inputDockBody, /minHeight=\{minimal \? 3 : 4\}/);
assert.match(inputDockBody, /<PromptInput[\s\S]*\/>\s*<\/Box>\s*<\/Box>\s*<Box height=\{1\} paddingX=\{1\} flexDirection="row">/);

const modeRowStart = inputDockBody.indexOf('<Box height={1} paddingX={1} flexDirection="row">');
const modeRowEnd = inputDockBody.indexOf('                </>', modeRowStart);
assert.ok(modeRowStart >= 0);
assert.ok(modeRowEnd > modeRowStart);

const modeRowBody = inputDockBody.slice(modeRowStart, modeRowEnd);
assert.match(modeRowBody, /spotifyMode\?\.enabled \? \(/);
assert.match(modeRowBody, /<Text bold color=\{SPOTIFY_GREEN\}>\{spotifyModeBorderLabel\}<\/Text>/);
assert.doesNotMatch(modeRowBody, /backgroundColor=/);
assert.doesNotMatch(modeRowBody, /SPOTIFY_SELECTED_TEXT/);
assert.doesNotMatch(inputDockBody, /----Spotify Mode----/);
assert.match(inputDockBody, /<CompactSetup[\s\S]*input=\{input\}[\s\S]*onSubmit=\{onSubmit\}/);
assert.match(inputDockBody, /setupPanel \? <CompactSetup/);
assert.match(source, /setupDoneHint\(setupPanel, language\)/);
assert.match(source, /setupMessageColor\(setupPanel\)/);
assert.match(source, /language === "zh-CN" \? "按Esc键隐藏" : "press Esc to hide"/);
assert.match(source, /text\.includes\("failed"\) \|\| text\.includes\("失败"\)/);
assert.match(source, /text\.includes\("connected"\) \|\| text\.includes\("success"\) \|\| text\.includes\("成功"\)/);
assert.match(source, /PromptInput[\s\S]*placeholder=\{setupPanel\.prompt \?\? inputPlaceholder\}/);

assert.match(appSource, /const isModelPanelActive = authSetup\?\.active && authSetup\.step === "model"/);
assert.match(appSource, /const \[spotifyMode, setSpotifyMode\] = useState<SpotifyModeState>/);
assert.match(appSource, /spotifyMode\.enabled\s*\?\s*spotifyModeSlashCommands\(input, language\)\s*:\s*slashCommandSuggestions\(input, language\)/);
assert.match(appSource, /const visibleConfirmChoices = React\.useMemo\(\(\) => confirm \? getVisibleConfirmChoices\(confirm\.choices\) : \[\], \[confirm\]\);/);
assert.match(appSource, /const selectedConfirmChoice = visibleConfirmChoices\[Math\.min\(confirmIndex, Math\.max\(0, visibleConfirmChoices\.length - 1\)\)\] \?\? null;/);
assert.match(appSource, /const decision = resolveConfirmDecisionFromInput\(text, visibleConfirmChoices\);/);
assert.match(appSource, /setConfirmIndex\(\(prev\) => visibleConfirmChoices\.length > 0 \? Math\.min\(visibleConfirmChoices\.length - 1, prev \+ 1\) : 0\);/);
assert.match(appSource, /const isLoginScreenActive = isGenericAuthSetup\(authSetup\) && !isModelPanelActive/);
assert.match(appSource, /\[language,[\s\S]*filter\(\(choice\) => choice !== language\)/);
assert.match(appSource, /setLanguagePanelIndex\(0\);/);
assert.match(appSource, /completeSlashCommand\(selectedHelpCommand\)/);
assert.match(appSource, /send\(\{ type: "auth_setup_input", value: "__cancel__" \}\)/);
assert.match(appSource, /case "spotify_mode":/);
assert.match(appSource, /setSpotifyMode\(\{ enabled: evt\.enabled, device_id: evt\.device_id, device_name: evt\.device_name \}\);/);
assert.match(appSource, /if \(spotifySetup && spotifySetup\.active === false && key\.escape\) \{\s*setSpotifySetup\(null\);/);
