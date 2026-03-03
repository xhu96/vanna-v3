import { useState } from 'react';
import { Play, AlertTriangle, Workflow, Box } from 'lucide-react';
import { TabList, Tab, Button, Textarea, Input, Card } from '@fluentui/react-components';

export function DevView() {
  const [activeTab, setActiveTab] = useState<'sql' | 'dbt' | 'flink' | 'cube'>('sql');

  return (
    <div className="flex flex-col h-full bg-[#202020]">
      {/* Fluent Toolbar */}
      <div className="bg-[#202020] border-b border-white/10 px-6 h-[48px] shrink-0 flex items-center">
        <TabList 
          selectedValue={activeTab} 
          onTabSelect={(_, data) => setActiveTab(data.value as 'sql')}
          appearance="subtle"
        >
          <Tab value="sql">SQL Scratchpad</Tab>
          <Tab value="dbt">dbt Pipeline</Tab>
          <Tab value="flink">Streaming Service</Tab>
          <Tab value="cube">Semantic Rules</Tab>
        </TabList>
      </div>

      {/* Editor Content */}
      <main className="flex-1 p-8 overflow-y-auto">
        {activeTab === 'sql' && (
          <div className="h-full flex flex-col space-y-4 max-w-6xl mx-auto">
            <div className="flex justify-between items-center bg-[#2d2d2d] p-3 rounded-t-lg border border-white/10 border-b-0 w-full">
              <span className="text-[13px] font-semibold text-white">SQL Workspace</span>
              <Button appearance="primary" icon={<Play size={14} fill="currentColor" />} size="small">
                Execute
              </Button>
            </div>
            <Textarea 
              className="flex-1 font-mono text-[13px] leading-relaxed resize-none shadow-inner [&>textarea]:p-5"
              style={{ tabSize: 4 }}
              value="SELECT &#10;    user_id, &#10;    COUNT(order_id) as total_orders&#10;FROM raw_orders&#10;WHERE created_at >= NOW() - INTERVAL '30 days'&#10;GROUP BY 1;"
            />
            <Card className="h-[220px] bg-[#1a1a1a] p-4 text-[13px] text-[#a6a6a6] font-mono rounded-lg overflow-y-auto w-full">
              <div className="mb-2 text-white">Execution Output</div>
              <div className="text-[#54b054]">&gt; Connected to Engine...</div>
              <div>&gt; Waiting for command...</div>
            </Card>
          </div>
        )}

        {/* ... remaining tabs converted to Fluent aesthetics ... */}
        {activeTab === 'dbt' && (
          <div className="max-w-5xl mx-auto w-full space-y-6">
            <h2 className="text-xl font-semibold text-white flex items-center space-x-2 pb-4 border-b border-white/10">
              <Workflow size={20} className="text-[#479ef5]" />
              <span>Declarative dbt Engine</span>
            </h2>
            
            <div className="grid grid-cols-2 gap-8">
              <div className="space-y-4">
                <label className="text-[14px] text-white">Pipeline Specification</label>
                <Textarea 
                  className="w-full text-[13px] h-48 resize-none"
                  placeholder="e.g. Create a daily staging model that cleans the raw_events table."
                />
                <Button appearance="primary">
                  Initialize Generation
                </Button>
              </div>
              <div className="flex flex-col space-y-4">
                <label className="text-[14px] text-white">Compiled Artifacts</label>
                <Card className="flex-1 bg-[#1a1a1a] rounded-[4px] font-mono text-[13px] p-4 text-[#a6a6a6] flex items-center justify-center">
                  Artifacts will appear here.
                </Card>
              </div>
            </div>
          </div>
        )}

        {activeTab === 'flink' && (
          <div className="max-w-5xl mx-auto w-full space-y-6">
            <div className="bg-[#fff4ce]/10 border border-[#fbd34d]/50 p-4 rounded-[4px] flex items-start space-x-3">
              <AlertTriangle className="text-[#fbd34d] mt-0.5 shrink-0" size={16} />
              <div>
                <h3 className="text-[13px] font-semibold text-white">Streaming Environment</h3>
                <p className="text-[13px] text-[#a6a6a6] mt-1">Queries are deployed directly to the Flink job manager. Results stream in real-time.</p>
              </div>
            </div>
            
            <div className="flex flex-col space-y-4">
               <Textarea 
                 className="w-full h-48 font-mono text-[13px] resize-none"
                 value="CREATE VIEW realtime_fraud_alerts AS&#10;SELECT user_id, amount, event_time&#10;FROM Transactions&#10;WHERE amount > 10000;"
               />
               <div className="flex justify-end">
                  <Button icon={<Play size={14} fill="currentColor" />} appearance="secondary">
                    Deploy stream job
                  </Button>
               </div>
            </div>
          </div>
        )}

        {activeTab === 'cube' && (
          <div className="max-w-4xl mx-auto w-full space-y-6 pt-10">
            <h2 className="text-xl font-semibold text-white flex items-center space-x-2 justify-center pb-2">
              <Box size={22} className="text-[#479ef5]" />
              <span>Semantic Resolution Inspector</span>
            </h2>
            <p className="text-center text-[13px] text-[#a6a6a6] max-w-xl mx-auto mb-8">
              Verify how natural language requests form structural ASTs against Cube.dev before falling through to direct warehouse execution.
            </p>
            
            <div className="flex space-x-3 w-full">
               <Input className="flex-1 min-w-[300px]" placeholder="Enter metric alias (e.g. active_users)" />
               <Button appearance="primary">Inspect</Button>
            </div>

            <Card className="h-[250px] bg-[#1a1a1a] rounded-[4px] font-mono text-[13px] flex items-center justify-center text-[#a6a6a6]">
               Waiting for trace input.
            </Card>
          </div>
        )}
      </main>
    </div>
  );
}


