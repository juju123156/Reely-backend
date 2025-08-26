package com.reely.service;

import com.reely.dto.RecordDto;

import java.util.List;

public interface RecordService {
    List<RecordDto> getRecordList(RecordDto recordDto);

    Long saveRecord(RecordDto recordDto);

    RecordDto getRecord(RecordDto recordDto);

    void updateRecord(RecordDto recordDto);
}
