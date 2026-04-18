import { VRMExpressionPresetName } from "@pixiv/three-vrm";

export type Message = {
  role: "assistant" | "system" | "user";
  content: string;
};

const talkStyles = ["talk", "happy", "sad", "angry", "fear", "surprised"] as const;
export type TalkStyle = (typeof talkStyles)[number];

export type Talk = {
  style: TalkStyle;
  speakerX: number;
  speakerY: number;
  message: string;
};

const emotions = ["neutral", "happy", "angry", "sad", "relaxed"] as const;
type EmotionType = (typeof emotions)[number] & VRMExpressionPresetName;

export type Screenplay = {
  expression: EmotionType;
  talk: Talk;
};
