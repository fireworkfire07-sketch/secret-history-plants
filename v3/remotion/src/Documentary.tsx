import React, {useEffect, useMemo, useState} from 'react';
import {
	AbsoluteFill,
	Audio,
	continueRender,
	delayRender,
	Easing,
	Img,
	interpolate,
	Sequence,
	spring,
	staticFile,
	useCurrentFrame,
	useVideoConfig,
} from 'remotion';
import type {Caption, Chapter, OnScreenText, Shot, Timeline} from './types';

const GOLD = '#F2C14E';
const XFADE = 12; // frames of cross-dissolve between shots

// ------------------------------------------------------------------ fonts
const FONT_CSS = `
@font-face {font-family: 'Anton'; src: url('${staticFile('fonts/Anton-Regular.ttf')}');}
@font-face {font-family: 'Montserrat'; src: url('${staticFile('fonts/Montserrat-VF.ttf')}'); font-weight: 100 900;}
@font-face {font-family: 'Crimson'; src: url('${staticFile('fonts/CrimsonText-SemiBoldItalic.ttf')}'); font-style: italic;}
`;

const useFonts = () => {
	const [handle] = useState(() => delayRender('fonts'));
	useEffect(() => {
		Promise.all([
			document.fonts.load('40px Anton'),
			document.fonts.load('800 40px Montserrat'),
			document.fonts.load('italic 40px Crimson'),
		])
			.catch(() => undefined)
			.finally(() => continueRender(handle));
	}, [handle]);
};

// ------------------------------------------------------------------ shots
const MOTIONS = [
	{s: [1.04, 1.16], x: [0, 0], y: [0, 0]},
	{s: [1.16, 1.04], x: [0, 0], y: [0, 0]},
	{s: [1.12, 1.12], x: [-3.5, 3.5], y: [0, 0]},
	{s: [1.12, 1.12], x: [3.5, -3.5], y: [0, 0]},
	{s: [1.06, 1.15], x: [-2, 2], y: [1.5, -1.5]},
	{s: [1.15, 1.07], x: [2, -1], y: [-1.5, 1]},
];

const ShotLayer: React.FC<{shot: Shot}> = ({shot}) => {
	const frame = useCurrentFrame();
	const total = shot.dur + XFADE;
	const m = MOTIONS[shot.seed % MOTIONS.length];
	const p = interpolate(frame, [0, total], [0, 1], {
		extrapolateRight: 'clamp',
		easing: Easing.inOut(Easing.sin),
	});
	const scale = m.s[0] + (m.s[1] - m.s[0]) * p;
	const x = m.x[0] + (m.x[1] - m.x[0]) * p;
	const y = m.y[0] + (m.y[1] - m.y[0]) * p;
	const opacity = interpolate(frame, [0, XFADE], [0, 1], {extrapolateRight: 'clamp'});
	const src = staticFile(shot.src);

	if (shot.fit === 'contain') {
		// archival documents/portraits: blurred fill + framed original
		return (
			<AbsoluteFill style={{opacity}}>
				<Img
					src={src}
					style={{
						width: '100%',
						height: '100%',
						objectFit: 'cover',
						filter: 'blur(38px) brightness(0.38) saturate(0.8)',
						transform: 'scale(1.2)',
					}}
				/>
				<AbsoluteFill style={{justifyContent: 'center', alignItems: 'center'}}>
					<Img
						src={src}
						style={{
							maxWidth: '78%',
							maxHeight: '82%',
							objectFit: 'contain',
							transform: `scale(${0.96 + (scale - 1) * 0.5}) translate(${x * 0.4}%, ${y * 0.4}%)`,
							boxShadow: '0 30px 90px rgba(0,0,0,0.75)',
							filter: 'sepia(0.12) contrast(1.05)',
						}}
					/>
				</AbsoluteFill>
			</AbsoluteFill>
		);
	}
	return (
		<AbsoluteFill style={{opacity, overflow: 'hidden'}}>
			<Img
				src={src}
				style={{
					width: '100%',
					height: '100%',
					objectFit: 'cover',
					transform: `scale(${scale}) translate(${x}%, ${y}%)`,
				}}
			/>
		</AbsoluteFill>
	);
};

// ------------------------------------------------------------------ grade, grain, vignette
const Grade: React.FC = () => {
	const frame = useCurrentFrame();
	return (
		<>
			<AbsoluteFill
				style={{
					background:
						'linear-gradient(180deg, rgba(10,30,40,0.18) 0%, rgba(0,0,0,0) 40%, rgba(60,30,0,0.10) 100%)',
					mixBlendMode: 'soft-light',
				}}
			/>
			<AbsoluteFill
				style={{
					background: 'radial-gradient(ellipse at center, rgba(0,0,0,0) 52%, rgba(0,0,0,0.62) 100%)',
				}}
			/>
			<AbsoluteFill style={{opacity: 0.11, mixBlendMode: 'overlay'}}>
				<svg width="100%" height="100%">
					<filter id={`g${frame % 8}`}>
						<feTurbulence type="fractalNoise" baseFrequency="0.85" numOctaves="2" seed={frame % 8} />
					</filter>
					<rect width="100%" height="100%" filter={`url(#g${frame % 8})`} />
				</svg>
			</AbsoluteFill>
		</>
	);
};

// ------------------------------------------------------------------ captions
type Chunk = {words: Caption['words']; from: number; to: number};

const chunkWords = (c: Caption): Chunk[] => {
	const chunks: Chunk[] = [];
	let cur: Caption['words'] = [];
	c.words.forEach((w, i) => {
		cur.push(w);
		const end = /[.,;:!?—]$/.test(w.w) || cur.length >= 5 || i === c.words.length - 1;
		if (end) {
			chunks.push({words: cur, from: cur[0].from, to: w.from + w.dur});
			cur = [];
		}
	});
	return chunks;
};

const CaptionBeat: React.FC<{c: Caption}> = ({c}) => {
	const frame = useCurrentFrame();
	const {fps} = useVideoConfig();
	const chunks = useMemo(() => chunkWords(c), [c]);
	let idx = chunks.findIndex((ch, i) => frame < (chunks[i + 1]?.from ?? Infinity));
	if (idx < 0) idx = chunks.length - 1;
	const ch = chunks[idx];
	if (!ch) return null;
	const pop = spring({frame: frame - ch.from, fps, config: {damping: 14, stiffness: 180}});
	return (
		<AbsoluteFill style={{justifyContent: 'flex-end', alignItems: 'center', paddingBottom: 96}}>
			<div
				style={{
					fontFamily: 'Montserrat',
					fontWeight: 800,
					fontSize: 60,
					lineHeight: 1.15,
					color: 'white',
					textAlign: 'center',
					maxWidth: 1500,
					transform: `translateY(${(1 - pop) * 18}px) scale(${0.94 + pop * 0.06})`,
					opacity: Math.min(1, pop * 1.4),
					textShadow: '0 4px 18px rgba(0,0,0,0.9), 0 0 3px rgba(0,0,0,0.9)',
				}}
			>
				{ch.words.map((w, i) => {
					const active = frame >= w.from && frame < w.from + w.dur + 2;
					const said = frame >= w.from;
					return (
						<span
							key={i}
							style={{
								display: 'inline-block',
								margin: '0 9px',
								color: w.e ? GOLD : active ? '#FFFFFF' : said ? '#F4F1EA' : 'rgba(255,255,255,0.55)',
								transform: active ? 'scale(1.08)' : 'scale(1)',
							}}
						>
							{w.w}
						</span>
					);
				})}
			</div>
		</AbsoluteFill>
	);
};

// ------------------------------------------------------------------ kinetic on-screen text
const KineticText: React.FC<{t: OnScreenText}> = ({t}) => {
	const frame = useCurrentFrame();
	const {fps} = useVideoConfig();
	const inn = spring({frame, fps, config: {damping: 16, stiffness: 140}});
	const out = interpolate(frame, [t.dur - 10, t.dur], [1, 0], {extrapolateLeft: 'clamp', extrapolateRight: 'clamp'});
	const line = interpolate(frame, [4, 22], [0, 1], {extrapolateLeft: 'clamp', extrapolateRight: 'clamp', easing: Easing.out(Easing.cubic)});
	const big = t.kind === 'number' || t.kind === 'date';
	return (
		<AbsoluteFill style={{justifyContent: 'flex-start', alignItems: 'flex-start', padding: '120px 130px', opacity: out}}>
			<div style={{transform: `translateX(${(1 - inn) * -60}px)`, opacity: inn}}>
				<div
					style={{
						fontFamily: 'Anton',
						fontSize: big ? 150 : 96,
						lineHeight: 1,
						color: big ? GOLD : '#FFFFFF',
						letterSpacing: `${(1 - inn) * 18 + 2}px`,
						textTransform: 'uppercase',
						textShadow: '0 8px 40px rgba(0,0,0,0.85)',
					}}
				>
					{t.kind === 'place' ? '◉ ' : ''}
					{t.value}
				</div>
				<div style={{height: 5, width: `${line * 100}%`, background: GOLD, margin: '14px 0 12px'}} />
				{t.label ? (
					<div
						style={{
							fontFamily: 'Montserrat',
							fontWeight: 700,
							fontSize: 30,
							letterSpacing: 6,
							color: '#EDE6D6',
							textTransform: 'uppercase',
							textShadow: '0 3px 14px rgba(0,0,0,0.9)',
						}}
					>
						{t.label}
					</div>
				) : null}
			</div>
		</AbsoluteFill>
	);
};

// ------------------------------------------------------------------ chapter card
const ChapterCard: React.FC<{c: Chapter}> = ({c}) => {
	const frame = useCurrentFrame();
	const {fps} = useVideoConfig();
	const bg = interpolate(frame, [0, 8, c.dur - 12, c.dur], [0, 0.78, 0.78, 0], {extrapolateRight: 'clamp'});
	const t1 = spring({frame: frame - 4, fps, config: {damping: 18}});
	const t2 = spring({frame: frame - 14, fps, config: {damping: 18}});
	const fade = interpolate(frame, [c.dur - 12, c.dur], [1, 0], {extrapolateLeft: 'clamp', extrapolateRight: 'clamp'});
	const line = interpolate(frame, [6, 30], [0, 420], {extrapolateLeft: 'clamp', extrapolateRight: 'clamp', easing: Easing.out(Easing.cubic)});
	return (
		<AbsoluteFill style={{background: `rgba(5,8,6,${bg})`, justifyContent: 'center', alignItems: 'center', opacity: fade}}>
			<div style={{textAlign: 'center'}}>
				<div style={{fontFamily: 'Montserrat', fontWeight: 600, fontSize: 28, letterSpacing: 14, color: GOLD, opacity: t1}}>
					CHAPTER {['I', 'II', 'III', 'IV', 'V', 'VI'][c.index - 1] ?? c.index}
				</div>
				<div
					style={{
						fontFamily: 'Anton',
						fontSize: 130,
						color: 'white',
						textTransform: 'uppercase',
						letterSpacing: 4,
						transform: `translateY(${(1 - t1) * 40}px)`,
						opacity: t1,
						margin: '10px 0 18px',
					}}
				>
					{c.title}
				</div>
				<div style={{height: 3, width: line, background: GOLD, margin: '0 auto 26px'}} />
				<div style={{fontFamily: 'Crimson', fontStyle: 'italic', fontSize: 50, color: '#EDE6D6', maxWidth: 1300, opacity: t2}}>
					{c.question}
				</div>
			</div>
		</AbsoluteFill>
	);
};

// ------------------------------------------------------------------ open-loop badge
const QuestionBadge: React.FC<{text: string; start: number; end: number; chapters: Chapter[]}> = ({text, start, end, chapters}) => {
	const frame = useCurrentFrame();
	if (!text || frame < start || frame > end + 20) return null;
	const inChapterCard = chapters.some((c) => frame >= c.from && frame < c.from + c.dur);
	const appear = interpolate(frame, [start, start + 18], [0, 1], {extrapolateRight: 'clamp'});
	const leave = interpolate(frame, [end, end + 20], [1, 0], {extrapolateLeft: 'clamp', extrapolateRight: 'clamp'});
	const pulse = 0.85 + 0.15 * Math.sin(frame / 14);
	return (
		<AbsoluteFill style={{justifyContent: 'flex-start', alignItems: 'flex-end', padding: '46px 56px'}}>
			<div
				style={{
					opacity: appear * leave * (inChapterCard ? 0 : 1),
					display: 'flex',
					alignItems: 'center',
					gap: 14,
					background: 'rgba(8,10,8,0.62)',
					border: `2px solid rgba(242,193,78,${0.5 + 0.4 * pulse})`,
					borderRadius: 40,
					padding: '10px 26px 10px 12px',
					backdropFilter: 'blur(6px)',
				}}
			>
				<div
					style={{
						width: 40,
						height: 40,
						borderRadius: 20,
						background: GOLD,
						color: '#111',
						fontFamily: 'Anton',
						fontSize: 30,
						display: 'flex',
						justifyContent: 'center',
						alignItems: 'center',
						transform: `scale(${pulse})`,
					}}
				>
					?
				</div>
				<div style={{fontFamily: 'Montserrat', fontWeight: 800, fontSize: 24, letterSpacing: 2, color: 'white'}}>{text}</div>
			</div>
		</AbsoluteFill>
	);
};

// ------------------------------------------------------------------ flash on hits
const Flash: React.FC = () => {
	const frame = useCurrentFrame();
	const o = interpolate(frame, [0, 2, 9], [0, 0.45, 0], {extrapolateRight: 'clamp'});
	return <AbsoluteFill style={{background: '#FFF6E0', opacity: o}} />;
};

// ------------------------------------------------------------------ end card
const EndCard: React.FC<{title: string}> = ({title}) => {
	const frame = useCurrentFrame();
	const o = interpolate(frame, [0, 20], [0, 1], {extrapolateRight: 'clamp'});
	return (
		<AbsoluteFill style={{background: `rgba(0,0,0,${o * 0.85})`, justifyContent: 'center', alignItems: 'center'}}>
			<div style={{opacity: o, textAlign: 'center'}}>
				<div style={{fontFamily: 'Montserrat', fontWeight: 600, fontSize: 26, letterSpacing: 12, color: GOLD}}>THE SECRET HISTORY OF PLANTS</div>
				<div style={{fontFamily: 'Crimson', fontStyle: 'italic', fontSize: 44, color: '#EDE6D6', marginTop: 18}}>{title}</div>
			</div>
		</AbsoluteFill>
	);
};

// ------------------------------------------------------------------ music ducking
const makeDucker = (speech: [number, number][]) => {
	const starts = speech.map((s) => s[0]);
	const talking = (f: number) => {
		let lo = 0;
		let hi = starts.length - 1;
		let k = -1;
		while (lo <= hi) {
			const mid = (lo + hi) >> 1;
			if (starts[mid] <= f) {
				k = mid;
				lo = mid + 1;
			} else hi = mid - 1;
		}
		return k >= 0 && f < speech[k][1];
	};
	return (f: number) => {
		let n = 0;
		for (let d = -9; d <= 9; d += 3) if (talking(f + d)) n++;
		return 0.24 - 0.15 * (n / 7);
	};
};

// ------------------------------------------------------------------ main
export const Documentary: React.FC<Timeline> = (t) => {
	useFonts();
	const duck = useMemo(() => makeDucker(t.speech || []), [t.speech]);
	const badgeStart = t.chapters[0]?.from ?? 300;
	return (
		<AbsoluteFill style={{background: '#000'}}>
			<style>{FONT_CSS}</style>
			<AbsoluteFill style={{filter: 'contrast(1.08) saturate(0.9) sepia(0.06)'}}>
				{t.shots.map((s, i) => (
					<Sequence key={i} from={s.from} durationInFrames={s.dur + XFADE} layout="none">
						<ShotLayer shot={s} />
					</Sequence>
				))}
			</AbsoluteFill>
			<Grade />
			{t.sfx
				.filter((s) => s.src.endsWith('hit.wav'))
				.map((s, i) => (
					<Sequence key={`f${i}`} from={s.from} durationInFrames={10}>
						<Flash />
					</Sequence>
				))}
			{t.texts.map((x, i) => (
				<Sequence key={`t${i}`} from={x.from} durationInFrames={x.dur}>
					<KineticText t={x} />
				</Sequence>
			))}
			{t.captions.map((c, i) => (
				<Sequence key={`c${i}`} from={c.from} durationInFrames={c.dur}>
					<CaptionBeat c={c} />
				</Sequence>
			))}
			<QuestionBadge text={t.badge} start={badgeStart} end={t.badgeEnd} chapters={t.chapters} />
			{t.chapters.map((c, i) => (
				<Sequence key={`ch${i}`} from={c.from} durationInFrames={c.dur}>
					<ChapterCard c={c} />
				</Sequence>
			))}
			<Sequence from={Math.max(0, t.durationInFrames - 75)}>
				<EndCard title={t.title} />
			</Sequence>

			{t.narration ? <Audio src={staticFile(t.narration)} /> : null}
			{t.music ? <Audio src={staticFile(t.music)} volume={(f) => duck(f)} /> : null}
			{t.sfx.map((s, i) => (
				<Sequence key={`s${i}`} from={s.from} durationInFrames={90}>
					<Audio src={staticFile(s.src)} volume={s.vol} />
				</Sequence>
			))}
		</AbsoluteFill>
	);
};
