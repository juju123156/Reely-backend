package com.reely.mapper;

import com.reely.dto.RecordDto;
import org.apache.ibatis.annotations.Mapper;

import java.util.List;

@Mapper
public interface RecordMapper {

    List<RecordDto> selectRecordList(RecordDto recordDto);
}
