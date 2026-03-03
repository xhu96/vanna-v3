import { useState, useRef, useEffect } from 'react';
import type { ReactNode } from 'react';
import { Send, BarChart2, Database, Zap, Terminal, Table as TableIcon, Shield } from 'lucide-react';
import { 
  Button, 
  Textarea, 
  Dialog, 
  DialogSurface, 
  DialogBody, 
  DialogTitle, 
  DialogContent, 
  Card,
  Spinner,
  Badge,
  Tooltip
} from '@fluentui/react-components';

type Message = {
  id: string;
  role: 'assistant' | 'user';
  content: string | ReactNode;
  metadata?: {
    confidence?: string;
    sources?: string[];
    piiScrubbed?: boolean;
    type?: 'text' | 'chart' | 'table';
  };
};

export function UserView() {
  const [query, setQuery] = useState('');
  const [isTyping, setIsTyping] = useState(false);
  const [activeDashboard, setActiveDashboard] = useState<string | null>(null);
  const chatEndRef = useRef<HTMLDivElement>(null);

  const [messages, setMessages] = useState<Message[]>([
    {
      id: '1',
      role: 'assistant',
      content: 'I am connected to your enterprise semantic models and governed data catalog. How can I help you analyze your metrics today?',
      metadata: { sources: ['Cube.dev', 'DataHub'] }
    }
  ]);

  const dashboards = [
    { title: "Q3 Revenue Trends", icon: <BarChart2 size={16} /> },
    { title: "Active Users by Region", icon: <Database size={16} /> },
    { title: "Product Conversion Rate", icon: <Zap size={16} /> }
  ];

  const scrollToBottom = () => {
    chatEndRef.current?.scrollIntoView({ behavior: 'smooth' });
  };

  useEffect(() => {
    scrollToBottom();
  }, [messages, isTyping]);

  const handleSend = (text: string) => {
    if (!text.trim()) return;
    
    const userMsg: Message = { id: Date.now().toString(), role: 'user', content: text };
    setMessages(prev => [...prev, userMsg]);
    setQuery('');
    setIsTyping(true);

    setTimeout(() => {
      setIsTyping(false);
      let responseContent: string | ReactNode = "I've queried the semantic layer for this information.";
      let type: 'text'|'chart'|'table' = 'text';

      const lowerText = text.toLowerCase();
      if (lowerText.includes('mqls by month') || lowerText.includes('mql')) {
        responseContent = (
          <Card className="mt-4 bg-[#2d2d2d] rounded-lg p-5 w-full flex flex-col items-center justify-center space-y-3">
            <BarChart2 size={32} className="text-[#a6a6a6]" strokeWidth={1.5} />
            <span className="text-white text-[13px] font-semibold">MQLs Grouped by Month</span>
            <div className="flex items-end space-x-3 h-24 w-full justify-center max-w-[200px] mt-2">
               <div className="w-8 bg-[#479ef5] h-10 rounded-t-[4px] opacity-70"></div>
               <div className="w-8 bg-[#479ef5] h-16 rounded-t-[4px] opacity-90"></div>
               <div className="w-8 bg-[#479ef5] h-20 rounded-t-[4px]"></div>
            </div>
          </Card>
        );
        type = 'chart';
      } else if (lowerText.includes('churn rate') || lowerText.includes('churn')) {
        responseContent = "The current overall churn rate is 2.4% for this quarter. This represents a 0.5% decrease compared to the previous quarter. Masking applied to 3 isolated user identities during the calculation.";
        type = 'text';
      } else if (lowerText.includes('sales vs marketing') || lowerText.includes('sales')) {
        responseContent = (
           <div className="mt-4">
             <p className="mb-3 text-[13px] text-white">Here is the tabular breakdown of Sales vs. Marketing Spend over the last 30 days:</p>
             <Card className="rounded-lg overflow-hidden bg-[#2d2d2d] p-0">
               <table className="w-full text-left text-[13px] border-collapse">
                 <thead className="bg-[#383838] text-white font-semibold border-b border-white/10">
                   <tr>
                     <th className="px-4 py-2.5 font-semibold">Metric</th>
                     <th className="px-4 py-2.5 font-semibold">Value</th>
                     <th className="px-4 py-2.5 font-semibold">MoM Δ</th>
                   </tr>
                 </thead>
                 <tbody className="divide-y divide-white/5 text-[#a6a6a6]">
                   <tr>
                     <td className="px-4 py-3">Total Sales</td>
                     <td className="px-4 py-3 text-white">$1.24M</td>
                     <td className="px-4 py-3 text-[#54b054]">+12%</td>
                   </tr>
                   <tr>
                     <td className="px-4 py-3">Marketing Spend</td>
                     <td className="px-4 py-3 text-white">$185k</td>
                     <td className="px-4 py-3 text-[#d13438]">-5%</td>
                   </tr>
                   <tr>
                     <td className="px-4 py-3">CAC</td>
                     <td className="px-4 py-3 text-white">$42.50</td>
                     <td className="px-4 py-3 text-[#54b054]">-15%</td>
                   </tr>
                 </tbody>
               </table>
             </Card>
           </div>
        );
        type = 'table';
      }

      setMessages(prev => [...prev, {
        id: Date.now().toString(),
        role: 'assistant',
        content: responseContent,
        metadata: {
          confidence: 'High',
          piiScrubbed: true,
          sources: ['Cube.dev'],
          type
        }
      }]);
    }, 1200);
  };

  return (
    <div className="flex h-full w-full bg-[#202020]">
      {/* Fluent Sidebar Container */}
      <aside className="w-[300px] bg-[#202020]/70 backdrop-blur-[40px] border-r border-white/10 flex flex-col p-4 shadow-xl z-20">
        
        {/* Navigation / Dashboards */}
        <div className="mb-8">
          <h2 className="text-[12px] font-semibold text-[#a6a6a6] px-2 mb-2 tracking-wide">Dashboards</h2>
          <div className="space-y-[2px]">
            {dashboards.map(d => (
              <DashboardCard 
                key={d.title}
                icon={d.icon} 
                title={d.title} 
                active={activeDashboard === d.title}
                onClick={() => setActiveDashboard(activeDashboard === d.title ? null : d.title)}
              />
            ))}
          </div>
        </div>

        {/* Global Details */}
        <div>
          <h2 className="text-[12px] font-semibold text-[#a6a6a6] px-2 mb-2 tracking-wide">Workspace Environment</h2>
          <Card className="bg-white/5 p-3 text-[12px] text-[#a6a6a6]">
            <div className="flex justify-between items-center bg-white/5 p-2 rounded mb-2">
              <span>Agent Layer</span>
              <span className="text-white flex items-center space-x-1"><div className="w-1.5 h-1.5 rounded-full bg-[#54b054]"></div> <span>Cube Router</span></span>
            </div>
            <div className="flex justify-between items-center bg-white/5 p-2 rounded mb-2">
              <span>Quality Rules</span>
              <span className="text-white">Active</span>
            </div>
            <div className="flex justify-between items-center bg-white/5 p-2 rounded">
              <span>Privacy Shield</span>
              <span className="text-white">Strict Rules</span>
            </div>
          </Card>
        </div>
      </aside>

      {/* Main Area */}
      <section className="flex-1 flex flex-col relative bg-[#202020]">
        
        {/* Dashboard Modal Overlay (Fluent Dialog) */}
        <Dialog open={!!activeDashboard} onOpenChange={(_, data) => !data.open && setActiveDashboard(null)}>
          <DialogSurface className="bg-[#2d2d2d] border border-white/10 rounded-xl min-w-[600px] shadow-2xl">
            <DialogBody>
              <DialogTitle className="text-white border-b border-white/10 pb-4 mb-4">{activeDashboard}</DialogTitle>
              <DialogContent className="p-10 flex flex-col items-center justify-center min-h-[300px]">
                 <BarChart2 size={48} className="text-[#a6a6a6] mb-4" strokeWidth={1} />
                 <p className="text-[14px] text-[#a6a6a6]">Live visualization powered by Semantic Models</p>
                 
                 <div className="w-64 h-[4px] border border-white/10 rounded-full overflow-hidden mt-6 bg-[#202020]">
                   <div className="h-full bg-[#479ef5] w-1/3 animate-[pulse_2s_ease-in-out_infinite]"></div>
                 </div>
              </DialogContent>
            </DialogBody>
          </DialogSurface>
        </Dialog>

        {/* Chat History Container */}
        <div className="flex-1 overflow-y-auto px-8 py-8">
          <div className="max-w-4xl mx-auto w-full space-y-8 pb-10">
            {messages.map((msg, index) => (
              <div key={msg.id} className={`flex ${msg.role === 'user' ? 'justify-end' : 'justify-start'}`}>
                {msg.role === 'assistant' ? (
                  <div className="max-w-[75%]">
                    {/* Assistant message body */}
                    <div className="flex items-start">
                        <div className="w-7 h-7 rounded bg-[#479ef5] flex items-center justify-center mt-0.5 shrink-0 shadow-sm mr-4 text-white">
                           <Terminal size={14} strokeWidth={2.5} />
                        </div>
                        <div className="flex flex-col space-y-1">
                          <span className="text-[12px] font-semibold text-white/90">Vanna Agent</span>
                          <div className="text-[14px] leading-relaxed text-white">
                            {msg.content}
                          </div>
                          
                          {/* Metadata / Tags */}
                          {msg.metadata && (
                            <div className="flex items-center space-x-2 pt-2 mt-2 flex-wrap gap-y-2">
                              {msg.metadata.type === 'chart' && <Badge color="informative" appearance="outline" icon={<BarChart2 size={12} />}>Chart Object</Badge>}
                              {msg.metadata.type === 'table' && <Badge color="informative" appearance="outline" icon={<TableIcon size={12} />}>Table Object</Badge>}
                              {msg.metadata.confidence && <Badge color="success" appearance="tint" icon={<Shield size={10} />}>{msg.metadata.confidence} Confidence</Badge>}
                              {msg.metadata.piiScrubbed && <Badge color="subtle" appearance="outline">Privacy Enforced</Badge>}
                            </div>
                          )}

                          {index === 0 && (
                            <div className="flex flex-wrap gap-2 pt-6">
                              <ActionChip text="Show MQLs by month" onClick={() => handleSend("Show MQLs by month")} />
                              <ActionChip text="Calculate overall churn" onClick={() => handleSend("Calculate overall churn rate")} />
                              <ActionChip text="Sales vs marketing spend" onClick={() => handleSend("Show me sales vs marketing spend")} />
                            </div>
                          )}
                        </div>
                    </div>
                  </div>
                ) : (
                  <div className="bg-white/10 text-white px-5 py-3 rounded-lg text-[14px] max-w-[75%] shadow-md">
                    {msg.content}
                  </div>
                )}
              </div>
            ))}

            {isTyping && (
              <div className="flex justify-start">
                <div className="flex items-start">
                  <div className="w-7 h-7 rounded bg-[#479ef5] flex items-center justify-center mt-0.5 shrink-0 shadow-sm mr-4 text-white">
                     <Terminal size={14} strokeWidth={2.5} />
                  </div>
                  <div className="flex flex-col space-y-1">
                    <span className="text-[12px] font-semibold text-white/90">Vanna Agent</span>
                    <div className="pt-1.5">
                      <Spinner size="extra-tiny" label="Thinking..." labelPosition="after" appearance="primary" />
                    </div>
                  </div>
                </div>
              </div>
            )}
            <div ref={chatEndRef} />
          </div>
        </div>

        {/* Input Area (Fluent Input Field) */}
        <div className="p-6 bg-[#202020] sticky bottom-0 border-t border-white/10">
          <div className="max-w-4xl mx-auto flex items-end bg-black/30 border border-white/10 flex-col overflow-hidden group focus-within:border-b-[#479ef5] rounded-[4px] transition-colors focus-within:border-b-2">
            <Textarea 
              rows={1}
              value={query}
              onChange={(e) => setQuery(e.target.value)}
              onKeyDown={(e) => {
                if (e.key === 'Enter' && !e.shiftKey) {
                  e.preventDefault();
                  if(query.trim() && !isTyping) handleSend(query);
                }
              }}
              placeholder="Ask a question about your data..."
              className="w-full bg-transparent text-white focus:outline-none resize-none max-h-[150px] border-none [&>textarea]:!shadow-none [&>textarea]:bg-transparent [&>textarea]:text-white [&>textarea]:p-4 [&>textarea]:focus:ring-0"
              style={{ minHeight: '52px' }}
              appearance="outline"
            />
            <div className="p-1 px-3 pb-2 w-full flex justify-between items-center bg-transparent">
              <span className="text-[11px] text-[#a6a6a6]">Powered by Vanna Engine v3.2</span>
              <Tooltip content="Send Message" relationship="label">
                <Button 
                  onClick={() => { if(query.trim() && !isTyping) handleSend(query); }}
                  disabled={!query.trim() || isTyping}
                  appearance={query.trim() && !isTyping ? "primary" : "subtle"}
                  icon={<Send size={14} className="ml-[1px]" />}
                  size="small"
                />
              </Tooltip>
            </div>
          </div>
        </div>
      </section>
    </div>
  );
}

function DashboardCard({ icon, title, active, onClick }: { icon: ReactNode, title: string, active: boolean, onClick: () => void }) {
  return (
    <button 
      onClick={onClick}
      className={`w-full flex items-center space-x-3 px-3 py-2.5 rounded-[4px] text-left transition-colors relative
        ${active 
          ? 'bg-white/10 text-white' 
          : 'text-white hover:bg-white/5'
        }`}
    >
      {active && <div className="absolute left-0 top-2 bottom-2 w-1 bg-[#479ef5] rounded-r-full"></div>}
      <span className={`${active ? 'text-[#479ef5]' : 'text-[#a6a6a6]'}`}>{icon}</span>
      <span className="text-[13px]">{title}</span>
    </button>
  );
}

function ActionChip({ text, onClick }: { text: string, onClick: () => void }) {
  return (
    <Button 
      onClick={onClick}
      appearance="secondary"
      size="small"
      className="text-[12px]"
    >
      {text}
    </Button>
  );
}
