// Shared types for LRMPageDashboard and its subcomponents.

export type Lang = 'fr' | 'en' | 'ru';
export const LANGS: Lang[] = ['fr', 'en', 'ru'];

export type Source = {
  sourceGuid: string; // lrm_sources.rowGUID -- stable id used as the AsyncStorage key suffix
  source_key: string;
  language: string;
  title: string;
  page_count: number | null;
  recognised_pages?: number;
};

export type BBox = { x: number; y: number; w: number; h: number }; // fractions of the page image
export type Word = { id: string; text: string; bbox: BBox; lang: string; style: string; char_start: number; char_end: number };
export type Block = { id: string; type: string; reading_order: number; text: string; words: Word[] };
export type PageDoc = {
  page: number; printed_page_number: string; image: string;
  image_size: { width: number; height: number }; blocks: Block[];
};
export type Hit = { block: Block; word: Word };
