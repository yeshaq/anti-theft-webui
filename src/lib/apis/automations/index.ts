import { WEBUI_API_BASE_URL } from '$lib/constants';

export type AutomationRun = {
	id: string;
	automation_id: string;
	chat_id: string | null;
	status: 'running' | 'success' | 'error';
	error: string | null;
	trigger: 'schedule' | 'manual';
	started_at: number;
	finished_at: number | null;
};

export type AutomationForm = {
	name: string;
	prompt: string;
	model_id: string;
	rrule: string;
	dtstart: number;
	timezone: string;
	options?: Record<string, any>;
	enabled: boolean;
};

export type Automation = AutomationForm & {
	id: string;
	user_id: string;
	next_run_at: number | null;
	last_run_at: number | null;
	run_count: number;
	created_at: number;
	updated_at: number;
	last_run: AutomationRun | null;
};

const request = async (token: string, path: string, method = 'GET', body?: object) => {
	let error = null;

	const res = await fetch(`${WEBUI_API_BASE_URL}/automations${path}`, {
		method,
		headers: {
			Accept: 'application/json',
			'Content-Type': 'application/json',
			authorization: `Bearer ${token}`
		},
		...(body ? { body: JSON.stringify(body) } : {})
	})
		.then(async (res) => {
			if (!res.ok) throw await res.json();
			return res.json();
		})
		.catch((err) => {
			error = err?.detail ?? `${err}`;
			console.log(err);
			return null;
		});

	if (error) {
		throw error;
	}

	return res;
};

export const getAutomations = async (token: string): Promise<Automation[]> => request(token, '/');

export const getAutomationById = async (token: string, id: string): Promise<Automation> =>
	request(token, `/${id}`);

export const getAutomationRuns = async (token: string, id: string): Promise<AutomationRun[]> =>
	request(token, `/${id}/runs`);

export const previewSchedule = async (
	token: string,
	schedule: { rrule: string; dtstart: number; timezone: string }
): Promise<{ occurrences: number[] }> => request(token, '/preview', 'POST', schedule);

export const createAutomation = async (token: string, form: AutomationForm): Promise<Automation> =>
	request(token, '/create', 'POST', form);

export const updateAutomationById = async (
	token: string,
	id: string,
	form: AutomationForm
): Promise<Automation> => request(token, `/${id}/update`, 'POST', form);

export const toggleAutomationById = async (token: string, id: string): Promise<Automation> =>
	request(token, `/${id}/toggle`, 'POST');

export const runAutomationById = async (token: string, id: string): Promise<Automation> =>
	request(token, `/${id}/run`, 'POST');

export const deleteAutomationById = async (token: string, id: string): Promise<boolean> =>
	request(token, `/${id}/delete`, 'DELETE');
