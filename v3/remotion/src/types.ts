export type Word = {w: string; from: number; dur: number; e: boolean};
export type Caption = {from: number; dur: number; words: Word[]};
export type Shot = {src: string; from: number; dur: number; fit: 'cover' | 'contain'; kind: string; seed: number};
export type OnScreenText = {from: number; dur: number; kind: string; value: string; label?: string};
export type Chapter = {from: number; dur: number; index: number; title: string; question: string};
export type Sfx = {src: string; from: number; vol: number};

export type Timeline = {
	fps: number;
	width: number;
	height: number;
	durationInFrames: number;
	title: string;
	badge: string;
	badgeEnd: number;
	narration: string;
	music: string | null;
	speech: [number, number][];
	shots: Shot[];
	captions: Caption[];
	texts: OnScreenText[];
	chapters: Chapter[];
	sfx: Sfx[];
};

export const emptyTimeline: Timeline = {
	fps: 30,
	width: 1920,
	height: 1080,
	durationInFrames: 90,
	title: 'The Secret History of Plants',
	badge: '',
	badgeEnd: 0,
	narration: '',
	music: null,
	speech: [],
	shots: [],
	captions: [],
	texts: [],
	chapters: [],
	sfx: [],
};
