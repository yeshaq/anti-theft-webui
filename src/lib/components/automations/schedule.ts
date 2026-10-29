// Turns the friendly schedule picker into an RRULE + start time for the backend.
// The picker state itself is stored in automation.options.schedule, so editing
// restores exactly what the user chose instead of reverse-parsing the RRULE.

export type ScheduleType = 'once' | 'hourly' | 'daily' | 'weekly' | 'monthly' | 'custom';

export type Schedule = {
	type: ScheduleType;
	time: string; // HH:mm, local to `timezone`
	date: string; // YYYY-MM-DD, used by "once"
	hours: number; // interval for "hourly"
	days: string[]; // RRULE weekday codes for "weekly"
	monthday: number; // 1-31 for "monthly"
	rrule: string; // raw rule for "custom"
};

export const WEEKDAYS = [
	{ code: 'MO', label: 'Mon' },
	{ code: 'TU', label: 'Tue' },
	{ code: 'WE', label: 'Wed' },
	{ code: 'TH', label: 'Thu' },
	{ code: 'FR', label: 'Fri' },
	{ code: 'SA', label: 'Sat' },
	{ code: 'SU', label: 'Sun' }
];

const pad = (n: number) => `${n}`.padStart(2, '0');

export const browserTimezone = () => Intl.DateTimeFormat().resolvedOptions().timeZone || 'UTC';

export const defaultSchedule = (): Schedule => {
	const now = new Date();
	return {
		type: 'daily',
		time: '09:00',
		date: `${now.getFullYear()}-${pad(now.getMonth() + 1)}-${pad(now.getDate())}`,
		hours: 6,
		days: ['MO', 'TU', 'WE', 'TH', 'FR'],
		monthday: now.getDate(),
		rrule: 'FREQ=WEEKLY;BYDAY=MO'
	};
};

const localEpoch = (date: string, time: string) => {
	const [y, m, d] = date.split('-').map(Number);
	const [hh, mm] = time.split(':').map(Number);
	return Math.floor(new Date(y, m - 1, d, hh, mm, 0, 0).getTime() / 1000);
};

const today = () => {
	const now = new Date();
	return `${now.getFullYear()}-${pad(now.getMonth() + 1)}-${pad(now.getDate())}`;
};

// dtstart is interpreted in the browser's timezone, which is also what we send
// as `timezone`, so the server expands the rule in the same wall clock.
export const toRule = (s: Schedule): { rrule: string; dtstart: number } => {
	const time = s.time || '09:00';

	switch (s.type) {
		case 'once':
			return { rrule: 'FREQ=DAILY;COUNT=1', dtstart: localEpoch(s.date || today(), time) };
		case 'hourly':
			return {
				rrule: `FREQ=HOURLY;INTERVAL=${Math.max(1, Math.min(23, Math.floor(s.hours || 1)))}`,
				dtstart: localEpoch(today(), time)
			};
		case 'weekly':
			return {
				rrule: `FREQ=WEEKLY;BYDAY=${(s.days.length ? s.days : ['MO']).join(',')}`,
				dtstart: localEpoch(today(), time)
			};
		case 'monthly':
			return {
				rrule: `FREQ=MONTHLY;BYMONTHDAY=${Math.max(1, Math.min(31, Math.floor(s.monthday || 1)))}`,
				dtstart: localEpoch(today(), time)
			};
		case 'custom':
			return {
				rrule: s.rrule.trim().replace(/^RRULE:/i, ''),
				dtstart: localEpoch(today(), time)
			};
		default:
			return { rrule: 'FREQ=DAILY', dtstart: localEpoch(today(), time) };
	}
};

export const describeSchedule = (s: Schedule | undefined, rrule: string): string => {
	if (!s) return rrule;

	switch (s.type) {
		case 'once':
			return `Once on ${s.date} at ${s.time}`;
		case 'hourly':
			return s.hours === 1 ? 'Every hour' : `Every ${s.hours} hours`;
		case 'daily':
			return `Every day at ${s.time}`;
		case 'weekly': {
			const labels = WEEKDAYS.filter((d) => s.days.includes(d.code)).map((d) => d.label);
			const weekdays = ['MO', 'TU', 'WE', 'TH', 'FR'];
			const isWeekdays = s.days.length === 5 && weekdays.every((d) => s.days.includes(d));
			return `${isWeekdays ? 'Weekdays' : labels.join(', ')} at ${s.time}`;
		}
		case 'monthly':
			return `Monthly on day ${s.monthday} at ${s.time}`;
		case 'custom':
			return `${s.rrule} (from ${s.time})`;
	}
	return rrule;
};
