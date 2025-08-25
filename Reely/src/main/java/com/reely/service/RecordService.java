package com.reely.service;

import com.reely.dto.RecordDto;

import java.util.List;

public interface RecordService {
    List<RecordDto> selectRecordList(RecordDto recordDto);
}
