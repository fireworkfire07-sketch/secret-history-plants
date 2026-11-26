import React from 'react';
import {Composition} from 'remotion';
import {Documentary} from './Documentary';
import {emptyTimeline, Timeline} from './types';

export const Root: React.FC = () => {
	return (
		<Composition
			id="Documentary"
			component={Documentary as unknown as React.FC<Record<string, unknown>>}
			defaultProps={emptyTimeline as unknown as Record<string, unknown>}
			durationInFrames={emptyTimeline.durationInFrames}
			fps={30}
			width={1920}
			height={1080}
			calculateMetadata={({props}) => {
				const t = props as unknown as Timeline;
				return {
					durationInFrames: Math.max(30, t.durationInFrames || 30),
					fps: t.fps || 30,
					width: t.width || 1920,
					height: t.height || 1080,
				};
			}}
		/>
	);
};
