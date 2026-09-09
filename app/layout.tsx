import type { Metadata } from 'next';
import './globals.css';
export const metadata: Metadata = {
  title: 'Fieldwork | Product Research',
  description:
    'Investigate e-commerce product ideas with a tool-calling research agent and traceable evidence.',
};
export default function RootLayout({
  children,
}: Readonly<{ children: React.ReactNode }>) {
  return (
    <html lang="en">
      <body>{children}</body>
    </html>
  );
}
