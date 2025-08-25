package com.reely.serviceImpl;

import com.reely.dto.RecordDto;
import com.reely.mapper.RecordMapper;
import com.reely.security.SecurityUtil;
import com.reely.service.RecordService;
import org.springframework.stereotype.Service;

import java.util.List;

@Service
public class RecordServiceImpl implements RecordService {

    private final RecordMapper recordMapper;

    public RecordServiceImpl(RecordMapper recordMapper) {
        this.recordMapper = recordMapper;
    }

    @Override
    public List<RecordDto> selectRecordList(RecordDto recordDto) {
        recordDto.setMemberPk(SecurityUtil.getCurrentMemberPk());
        return recordMapper.selectRecordList(recordDto);
    }
}
