#!/usr/bin/env python3
"""Apply identical observation-only hooks to disposable correctness sources.

No hooks enter the timed Release source. A missing anchor requires operator
review of the refactor; never silently skip an observation.
"""
from pathlib import Path


def instrument(source):
    source = Path(source)
    header = source / 'src/base/exam_trace.h'
    if header.exists():
        raise ValueError('source is already instrumented')
    header.write_text(r'''#pragma once
#include <cstdlib>
#include <fstream>
#include "base/request.h"
namespace Ramulator {
inline std::ofstream& exam_output() {
  static std::ofstream stream(std::getenv("EXAM_TRACE") ? std::getenv("EXAM_TRACE") : "/dev/null");
  return stream;
}
inline void exam_request(const char* event, long clock, const Request& req, int success = -1) {
  auto& out = exam_output();
  out << event << '\t' << clock << '\t' << req.exam_id << '\t' << success
      << '\t' << req.addr << '\t' << req.type_id << '\t' << req.command
      << '\t' << req.arrive << '\t' << req.depart;
  for (auto x : req.addr_vec) out << '\t' << x;
  out << '\n';
}
inline void exam_command(long clock, int command, const std::string& name, const AddrVec_t& address) {
  auto& out = exam_output();
  out << "command\t" << clock << '\t' << command << '\t' << name;
  for (auto x : address) out << '\t' << x;
  out << '\n';
}
}
''')
    def edit(relative, changes, include=False):
        path = source / relative
        text = path.read_text()
        for old, new in changes:
            if text.count(old) != 1:
                raise ValueError(f'instrumentation anchor changed in {relative}: {old[:70]}')
            text = text.replace(old, new)
        if include:
            text = '#include "base/exam_trace.h"\n' + text
        path.write_text(text)
    edit('src/base/request.h', [('struct Request {', 'struct Request {\n  long exam_id = 0;')])
    edit('src/memory_system/impl/generic_DRAM_system.cpp', [
        ('m_addr_mapper->apply(req);', 'req.exam_id = 1L + s_num_read_requests + s_num_write_requests + s_num_other_requests;\n      m_addr_mapper->apply(req);'),
        ('bool is_success = m_controllers[channel_id]->send(req);',
         'bool is_success = m_controllers[channel_id]->send(req);\n      exam_request("accept", m_clk, req, is_success);')], True)
    edit('src/dram_controller/impl/generic_dram_controller.cpp', [
        ('std::deque<Request> pending;', 'long exam_priority = 0;\n    std::deque<Request> pending;'),
        ('bool priority_send(Request& req) override {',
         'bool priority_send(Request& req) override {\n      req.exam_id = --exam_priority;'),
        ('is_success = m_priority_buffer.enqueue(req);',
         'is_success = m_priority_buffer.enqueue(req);\n      exam_request("priority", m_clk, req, is_success);'),
        ('bool request_found = schedule_request(req_it, buffer);',
         'bool request_found = schedule_request(req_it, buffer);\n      if (request_found) exam_request("select", m_clk, *req_it);'),
        ('if (req.callback) {', 'exam_request("complete", m_clk, req);\n          if (req.callback) {')], True)
    edit('src/dram/impl/DDR4.cpp', [
        ('void issue_command(int command, const AddrVec_t& addr_vec) override {',
         'void issue_command(int command, const AddrVec_t& addr_vec) override {\n      exam_command(m_clk, command, std::string(m_commands(command)), addr_vec);')], True)


if __name__ == '__main__':
    import sys
    instrument(Path(sys.argv[1]))
