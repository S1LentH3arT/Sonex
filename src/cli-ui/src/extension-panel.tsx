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
    if (action === "reset") return "#ef4444";
    if (action === "disable" || action === "repair" || action === "restart") return "#facc15";
    return PANEL_PRIMARY;
};

const extensionActionBold = (action: string): boolean => action === "reset" || action === "restart";

const detailAction = (detail: ExtensionDetail | null | undefined): string | null => {
    if (!detail || detail.status === "waiting" || detail.status === "unsupported") return null;
    if (detail.armed_action === "reset") return "Insist";
    if (detail.armed_action === "restart") return "Restart";
    return detail.action || null;
};

const statusLabel = (status: ExtensionStatus): string => STATUS_LABELS[status];

const dependencyGlyph = (state: ExtensionDependency["state"], spinnerFrame = 0): string => (
    state === "installed" ? "✔️" : state === "failed" ? "❌" : state === "installing" ? ["⠦", "⠴", "⠧", "⠇", "⠏", "⠋", "⠙", "⠹", "⠸", "⠼"][spinnerFrame % 10] : "□"
);

const dependencyColor = (state: ExtensionDependency["state"]): string => (
    state === "installed" ? "#22c55e" : state === "failed" ? "#ef4444" : state === "installing" ? "#808791" : "#808791"
);

const dependencyLine = (dependency: ExtensionDependency, labelWidth: number, spinnerFrame = 0): PanelRowSegment[] => {
    const glyph = dependencyGlyph(dependency.state, spinnerFrame);
    const paddedLabel = dependency.label + " ".repeat(Math.max(0, labelWidth - stringWidth(dependency.label) + 1));
    const suffix = dependency.state === "installing"
        ? `${"█".repeat(Math.max(1, Math.round(18 * Math.min(1, Math.max(0, dependency.progress ?? 0) / 100))))}${"░".repeat(Math.max(0, 18 - Math.round(18 * Math.min(1, Math.max(0, dependency.progress ?? 0) / 100))))}`
        : dependency.version || dependency.error || "";
    return [
        { text: `${glyph} ${paddedLabel}`, color: dependencyColor(dependency.state), bold: dependency.state === "failed", preserveColorWhenSelected: true },
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
    const action = detailAction(detail);
    const actions = detail.status === "waiting" || detail.status === "unsupported"
        ? []
        : detail.armed_action === "reset"
        ? [{ key: "confirm_reset", segments: [
            { text: "Insist", color: "#ef4444", bold: true, preserveColorWhenSelected: true },
            { text: "  local credentials will be deleted", color: "#facc15", preserveColorWhenSelected: true },
        ] }]
        : detail.armed_action === "restart"
            ? [{ key: "confirm_restart", segments: [
                { text: "Restart", color: "#facc15", bold: true, preserveColorWhenSelected: true },
                { text: "  configuration will be applied", color: PANEL_SECONDARY, preserveColorWhenSelected: true },
            ] }]
            : [
                { key: "quick_check", segments: [{ text: "Quick Check", color: PANEL_PRIMARY }] },
                ...(action ? [{ key: action, segments: [{ text: action === "setup" ? "Setup" : action === "enable" ? "Enable" : action === "disable" ? "Disable" : action === "repair" ? "Repair" : "Restart", color: extensionActionColor(action), bold: extensionActionBold(action), preserveColorWhenSelected: true }] }] : []),
                ...(detail.reset_available ? [{ key: "prepare_reset", segments: [{ text: "Reset", color: "#ef4444", bold: true, preserveColorWhenSelected: true }] }] : []),
            ];
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
        ) : setup.body.split("\n").map((line, index) => (
            <PanelRow key={`${index}-${line}`} width={width} segments={[{ text: line, color: PANEL_PRIMARY }]} />
        ))}
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
