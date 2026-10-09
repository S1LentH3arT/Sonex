import type { ChatHeaderVariant } from "./layout.js";
import type { ChatItem, ChatMessageItem, UiLanguage } from "./types.js";

export type TranscriptSurface = "main" | "alternate";

export type CommittedTranscriptRecord = Readonly<{
    sequence: number;
    item: ChatItem;
    presentation: TranscriptPresentation;
}>;

export type TranscriptPresentation = Readonly<{
    contentWidth: number;
    headerVariant: ChatHeaderVariant;
    language: UiLanguage;
}>;

export type TranscriptState = Readonly<{
    records: CommittedTranscriptRecord[];
    deferredRecords: CommittedTranscriptRecord[];
    nextSequence: number;
    pendingUserEchoes: Readonly<Record<string, number>>;
    surface: TranscriptSurface;
}>;

export type TranscriptAction =
    | { type: "commit"; items: ChatItem[]; presentation: TranscriptPresentation }
    | { type: "submitUser"; item: ChatMessageItem; presentation: TranscriptPresentation }
    | { type: "receiveUser"; item: ChatMessageItem; presentation: TranscriptPresentation }
    | { type: "rejectUserSend"; content: string }
    | { type: "setSurface"; surface: TranscriptSurface };

export type ServerEventTranscriptClass = "chat" | "error" | "transient";

export const createTranscriptState = (): TranscriptState => ({
    records: [],
    deferredRecords: [],
    nextSequence: 0,
    pendingUserEchoes: {},
    surface: "main",
});

const echoKey = (content: string): string => content.trim();

const appendItems = (
    state: TranscriptState,
    items: ChatItem[],
    presentation: TranscriptPresentation,
): TranscriptState => {
    if (items.length === 0) return state;

    const appended = items.map((item, index) => ({
        sequence: state.nextSequence + index,
        item,
        presentation,
    }));
    const nextSequence = state.nextSequence + appended.length;

    if (state.surface === "alternate") {
        return {
            ...state,
            deferredRecords: [...state.deferredRecords, ...appended],
            nextSequence,
        };
    }

    return {
        ...state,
        records: [...state.records, ...appended],
        nextSequence,
    };
};

const consumePendingEcho = (
    pendingUserEchoes: Readonly<Record<string, number>>,
    key: string,
): Readonly<Record<string, number>> | null => {
    const count = Object.hasOwn(pendingUserEchoes, key) ? pendingUserEchoes[key] ?? 0 : 0;
    if (count === 0) return null;

    const next = { ...pendingUserEchoes };
    if (count === 1) {
        delete next[key];
    } else {
        next[key] = count - 1;
    }
    return next;
};

export function transcriptReducer(
    state: TranscriptState,
    action: TranscriptAction,
): TranscriptState {
    switch (action.type) {
        case "commit":
            return appendItems(state, action.items, action.presentation);
        case "submitUser": {
            const key = echoKey(action.item.content);
            const count = Object.hasOwn(state.pendingUserEchoes, key)
                ? state.pendingUserEchoes[key] ?? 0
                : 0;
            const pendingUserEchoes = {
                ...state.pendingUserEchoes,
                [key]: count + 1,
            };
            return appendItems(
                { ...state, pendingUserEchoes },
                [action.item],
                action.presentation,
            );
        }
        case "receiveUser": {
            const pendingUserEchoes = consumePendingEcho(
                state.pendingUserEchoes,
                echoKey(action.item.content),
            );
            return pendingUserEchoes === null
                ? appendItems(state, [action.item], action.presentation)
                : { ...state, pendingUserEchoes };
        }
        case "rejectUserSend": {
            const pendingUserEchoes = consumePendingEcho(
                state.pendingUserEchoes,
                echoKey(action.content),
            );
            return pendingUserEchoes === null ? state : { ...state, pendingUserEchoes };
        }
        case "setSurface":
            if (action.surface === state.surface) return state;
            if (action.surface === "main") {
                return {
                    ...state,
                    records: [...state.records, ...state.deferredRecords],
                    deferredRecords: [],
                    surface: "main",
                };
            }
            return { ...state, surface: "alternate" };
    }
}

export const classifyServerEventForTranscript = (
    event: { type: string },
): ServerEventTranscriptClass => {
    if (event.type === "chat") return "chat";
    if (event.type === "error") return "error";
    return "transient";
};

export const allTranscriptItems = (state: TranscriptState): ChatItem[] => (
    [...state.records, ...state.deferredRecords]
        .sort((left, right) => left.sequence - right.sequence)
        .map((record) => record.item)
);
