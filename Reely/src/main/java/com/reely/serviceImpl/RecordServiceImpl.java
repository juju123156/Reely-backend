package com.reely.serviceImpl;

import com.reely.dto.RecordDto;
import com.reely.exception.CustomException;
import com.reely.exception.ErrorCode;
import com.reely.mapper.RecordMapper;
import com.reely.security.SecurityUtil;
import com.reely.service.RecordService;
import jakarta.transaction.Transactional;
import org.springframework.stereotype.Service;

import java.util.List;

@Service
public class RecordServiceImpl implements RecordService {

    private final RecordMapper recordMapper;

    public RecordServiceImpl(RecordMapper recordMapper) {
        this.recordMapper = recordMapper;
    }

    @Override
    public List<RecordDto> getRecordList(RecordDto recordDto) {
        recordDto.setMemberPk(SecurityUtil.getCurrentMemberPk());
        return recordMapper.selectRecordList(recordDto);
    }

    @Override
    @Transactional
    public Long saveRecord(RecordDto recordDto) {
        recordDto.setMemberPk(SecurityUtil.getCurrentMemberPk());
        recordMapper.insertRecord(recordDto);
        return recordDto.getRecordId();
    }

    @Override
    public RecordDto getRecord(RecordDto recordDto) {
        recordDto.setMemberPk(SecurityUtil.getCurrentMemberPk());
        return recordMapper.selectRecordByRecordIdAndMemberPk(recordDto);
    }

    @Override
    @Transactional
    public void updateRecord(RecordDto recordDto) {
        recordDto.setMemberPk(SecurityUtil.getCurrentMemberPk());
        Integer result = recordMapper.updateRecord(recordDto);
        if (result != 1) {
            throw new CustomException(ErrorCode.INTERNAL_ERROR, "1개 이상의 레코드가 수정되었습니다.");
        }
    }
}
