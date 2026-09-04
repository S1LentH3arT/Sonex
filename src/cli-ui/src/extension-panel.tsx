import React from "react";
import { Box, Text } from "ink";
import stringWidth from "string-width";
import TextInput from "ink-text-input";
import { PanelChoiceList, PanelFrame, PanelRow, PANEL_PRIMARY, PANEL_SECONDARY, type PanelChoiceItem, type PanelRowSegment } from "./panel-frame.js";
import type { ExtensionDependency, ExtensionDetail, ExtensionPanelState, ExtensionSetup, ExtensionStatus, ExtensionView } from "./types.js";

const SIGNAL_COLORS: Record<ExtensionView["signal"], string> = {
    green: "#22c55e",
    gray: "#808791",
    red: "#ef4444",
    yellow: "#facc15",
    hollow: "#808791",
};

const STATUS_LABELS: Record<ExtensionStatus, string> = {
    enabled: "Enabled",
    not_configured: "Not configured",
    disabled: "Disabled",
    unavailable: "Unavailable",
    unapplied: "Unapplied",
    unsupported: "Unsupported",
    waiting: "Waiting for response…",
};

export const EXTENSION_NAME_WIDTH = 7;

export const extensionSignal = (extension: ExtensionView): string => (
    extension.signal === "hollow" ? "◦" : "•"
);

const extensionActionColor = (action: string): string => {
    if (action === "reset" || action === "prepare_reset") return "#ef4444";
    if (action === "repair" || action === "restart" || action === "prepare_restart") return "#facc15";
    return PANEL_PRIMARY;
};

const extensionActionBold = (action: string): boolean => action === "restart" || action === "prepare_restart" || action === "prepare_reset";

const statusLabel = (status: ExtensionStatus): string => STATUS_LABELS[status];

const extensionActionLabel = (action: string): string => ({
    setup: "Setup",
    enable: "Enable",
    disable: "Disable",
    repair: "Repair",
    restart: "Restart",
    prepare_restart: "Restart",
    quick_check: "Quick Check",
    prepare_reset: "Reset",
    confirm_reset: "Insist",
    confirm_restart: "Restart",
}[action] || action);

const DEPENDENCY_MARKER_WIDTH = Math.max(stringWidth("✔️"), stringWidth("❌"), stringWidth("□"));
const DEPENDENCY_PROGRESS_WIDTH = 18;

const dependencyGlyph = (state: ExtensionDependency["state"], spinnerFrame = 0): string => (
    state === "installed" ? "✔️" : state === "failed" ? "❌" : state === "installing" ? ["⠦", "⠴", "⠧", "⠇", "⠏", "⠋", "⠙", "⠹", "⠸", "⠼"][spinnerFrame % 10] : "□"
);

const dependencyColor = (state: ExtensionDependency["state"]): string => (
    state === "installed" ? "#22c55e" : state === "failed" ? "#ef4444" : state === "installing" ? "#808791" : "#808791"
);

const dependencyProgressBar = (progress: number | null | undefined, spinnerFrame = 0): string => {
    if (progress == null) {
        const position = spinnerFrame % DEPENDENCY_PROGRESS_WIDTH;
        return `${"░".repeat(position)}█${"░".repeat(DEPENDENCY_PROGRESS_WIDTH - position - 1)}`;
    }
    const filled = Math.round(DEPENDENCY_PROGRESS_WIDTH * Math.min(1, Math.max(0, progress) / 100));
    return `${"█".repeat(Math.max(1, filled))}${"░".repeat(Math.max(0, DEPENDENCY_PROGRESS_WIDTH - Math.max(1, filled)))}`;
};

export const dependencyLine = (dependency: ExtensionDependency, labelWidth: number, spinnerFrame = 0): PanelRowSegment[] => {
    const glyph = dependencyGlyph(dependency.state, spinnerFrame);
    const marker = `${" ".repeat(Math.max(0, DEPENDENCY_MARKER_WIDTH - stringWidth(glyph)))}${glyph}`;
    const paddedLabel = dependency.label + " ".repeat(Math.max(0, labelWidth - stringWidth(dependency.label) + 1));
    const suffix = dependency.state === "installing"
        ? dependencyProgressBar(dependency.progress, spinnerFrame)
        : dependency.version || dependency.error || "";
    return [
        { text: `${marker} ${paddedLabel}`, color: dependencyColor(dependency.state), bold: dependency.state === "failed", preserveColorWhenSelected: true },
        { text: suffix ? ` ${suffix}` : "", color: dependency.state === "failed" ? "#ef4444" : dependency.state === "installing" ? "#808791" : PANEL_PRIMARY },
    ];
};

export const ExtensionPanelOverlay = ({
    panel,
    selectedIndex,
    width,
    input = "",
    setInput = () => undefined,
    onSubmit = () => undefined,
    inputFocus = false,
}: {
    panel: ExtensionPanelState;
    selectedIndex: number;
    width: number;
    input?: string;
    setInput?: (value: string) => void;
    onSubmit?: (value: string) => void;
    inputFocus?: boolean;
}) => {
    if (!panel) return null;
    if (panel.view === "list") {
        const items: PanelChoiceItem[] = panel.extensions.map((extension) => ({
            key: extension.id,
            segments: [
                { text: `${extensionSignal(extension)} `, color: SIGNAL_COLORS[extension.signal], preserveColorWhenSelected: true },
                { text: `${extension.name.padEnd(EXTENSION_NAME_WIDTH, " ")} `, color: PANEL_PRIMARY },
                { text: extension.description, color: PANEL_SECONDARY },
            ],
        }));
        return (
            <PanelFrame width={width} title={panel.title} hint={panel.hint || "↑/↓ select · Enter open · Esc close"}>
                <PanelChoiceList items={items} selectedIndex={selectedIndex} width={width} />
            </PanelFrame>
        );
    }

    if (panel.view === "setup" && panel.setup) {
        return <ExtensionSetupPanel setup={panel.setup} width={width} selectedIndex={selectedIndex} input={input} setInput={setInput} onSubmit={onSubmit} inputFocus={inputFocus} />;
    }

    const detail = panel.detail;
    const extension = panel.extensions.find((item) => item.id === panel.selectedExtension) || panel.extensions[selectedIndex];
    if (!detail || !extension) return null;
    const actions = (detail.actions ?? []).map((action) => {
        if (action === "confirm_reset") {
            return { key: action, segments: [
                { text: "Insist", color: "#ef4444", bold: true, preserveColorWhenSelected: true },
                { text: "  local credentials will be deleted", color: "#facc15", preserveColorWhenSelected: true },
            ] };
        }
        if (action === "confirm_restart") {
            return { key: action, segments: [
                { text: "Restart", color: "#facc15", bold: true, preserveColorWhenSelected: true },
                { text: "  configuration will be applied", color: PANEL_SECONDARY, preserveColorWhenSelected: true },
            ] };
        }
        return {
            key: action,
            selectedColor: action === "prepare_reset" ? "#ef4444" : undefined,
            segments: [{
                text: extensionActionLabel(action),
                color: extensionActionColor(action),
                bold: extensionActionBold(action),
                preserveColorWhenSelected: !["disable", "setup", "prepare_reset"].includes(action),
            }],
        };
    });
    const signalColor = SIGNAL_COLORS[extension.signal];
    return (
        <PanelFrame
            width={width}
            title={`${extensionSignal(extension)} ${extension.name}`}
            titleSegments={[
                { text: extensionSignal(extension), color: signalColor, bold: true },
                { text: ` ${extension.name}`, color: "#c8a6ff", bold: true },
            ]}
            hint={panel.hint || "↑/↓ select · Enter act · Esc back"}
        >
            <PanelRow width={width} segments={[{ text: `Status       ${statusLabel(detail.status)}`, color: detail.status === "waiting" ? PANEL_SECONDARY : PANEL_PRIMARY }]} />
            <PanelRow width={width} segments={[
                { text: "Tag          ", color: PANEL_PRIMARY },
                { text: extension.tags.join(" · "), color: "#183b8c", italic: true },
            ]} />
            <PanelChoiceList
                items={actions}
                selectedIndex={selectedIndex}
                width={width}
            />
        </PanelFrame>
    );
};

const ExtensionSetupPanel = ({
    setup,
    width,
    selectedIndex,
    input,
    setInput,
    onSubmit,
    inputFocus,
}: {
    setup: ExtensionSetup;
    width: number;
    selectedIndex: number;
    input: string;
    setInput: (value: string) => void;
    onSubmit: (value: string) => void;
    inputFocus: boolean;
}) => {
    const [spinnerFrame, setSpinnerFrame] = React.useState(0);
    React.useEffect(() => {
        if (!setup.dependencies?.some((dependency) => dependency.state === "installing")) return;
        const timer = setInterval(() => setSpinnerFrame((frame) => frame + 1), 100);
        return () => clearInterval(timer);
    }, [setup.dependencies]);
    return (
    <PanelFrame width={width} title={setup.title} hint="←/→ page · Enter submit · Esc back">
        {setup.body ? setup.body.split("\n").map((line, index) => (
            <PanelRow key={`${index}-${line}`} width={width} segments={[{ text: line, color: setup.dependencies ? PANEL_SECONDARY : PANEL_PRIMARY }]} />
        )) : null}
        {setup.dependencies ? (
            <>
                <PanelChoiceList
                    items={setup.dependencies.map((dependency) => ({
                        key: dependency.id,
                        segments: dependencyLine(dependency, Math.max(...setup.dependencies!.map((item) => stringWidth(item.label))), spinnerFrame),
                    }))}
                    selectedIndex={selectedIndex}
                    width={width}
                />
            </>
        ) : null}
        {setup.error ? <PanelRow width={width} segments={[{ text: setup.error, color: "#ff6b6b" }]} /> : null}
        {setup.input ? (
            <Box paddingX={1}>
                <Text color={PANEL_PRIMARY}>
                    <TextInput value={input} onChange={setInput} onSubmit={onSubmit} focus={inputFocus} showCursor={false} placeholder={setup.input.placeholder} mask={setup.input.mask ? "*" : undefined} />
                </Text>
            </Box>
        ) : null}
        <PanelRow width={width} segments={[{ text: `${setup.page}/${setup.page_count}`, color: PANEL_SECONDARY }]} />
    </PanelFrame>
    );
};
